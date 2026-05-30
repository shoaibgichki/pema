"""
Session lifecycle manager (PRD FR-05).

Handles creation, retrieval, state transitions, and closure of triage sessions.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.fact import SessionFact
from app.models.message import Message
from app.models.rule_event import RuleEvent
from app.models.model_audit import ModelAudit
from app.models.session import TriageSession
from app.schemas.enums import Language, SessionStatus, Urgency, SessionMode
from app.schemas.fact import ExtractedFacts


# ── Framing Messages (PRD FR-06.1, FR-06.2) ──────────────────────────────

FRAMING_MESSAGES = {
    Language.EN: (
        "Hi! I'm PEMA, your health guide. I can help you figure out what "
        "type of doctor to visit based on your symptoms.\n"
        "⚠️ I don't diagnose or prescribe. If this is an emergency, "
        "please call 1122 immediately.\n"
        "Tell me, what's bothering you today?"
    ),
    Language.UR: (
        "Assalam o Alaikum! Main PEMA hoon. Main aapko batata hoon ke "
        "aapko kis qisam ke doctor ke paas jana chahiye.\n"
        "⚠️ Main diagnose ya dawai nahi deta. Agar emergency hai to "
        "abhi 1122 call karein.\n"
        "Batayein, kya takleef hai?"
    ),
}

DOCTOR_FRAMING_MESSAGES = {
    Language.EN: (
        "PEMA Clinical Consultant Mode activated.\n"
        "⚠️ This is an AI consultation intended for clinical use. "
        "Verify all differential diagnoses and recommendations with your clinical judgment.\n"
        "Please describe the patient's presentation."
    ),
    Language.UR: (
        "PEMA Clinical Consultant Mode activated.\n"
        "⚠️ This is an AI consultation intended for clinical use. "
        "Verify all differential diagnoses and recommendations with your clinical judgment.\n"
        "Please describe the patient's presentation."
    ),
}


# ── Valid State Transitions ───────────────────────────────────────────────

_VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CONSENT_FRAMING: {
        SessionStatus.CHIEF_COMPLAINT,
        SessionStatus.ABANDONED,
    },
    SessionStatus.CHIEF_COMPLAINT: {
        SessionStatus.FACT_GATHERING,
        SessionStatus.ESCALATED,
        SessionStatus.ABANDONED,
    },
    SessionStatus.FACT_GATHERING: {
        SessionStatus.FACT_GATHERING,
        SessionStatus.SPECIALTY_ROUTING,
        SessionStatus.ESCALATED,
        SessionStatus.ABANDONED,
    },
    SessionStatus.SPECIALTY_ROUTING: {
        SessionStatus.COMPLETED,
        SessionStatus.ESCALATED,
        SessionStatus.ABANDONED,
    },
    SessionStatus.COMPLETED: set(),
    SessionStatus.ESCALATED: set(),
    SessionStatus.ABANDONED: set(),
}


# ── Public API ────────────────────────────────────────────────────────────


async def create_session(
    db: AsyncSession,
    language: Language = Language.EN,
    channel: str = "web",
    mode: SessionMode = SessionMode.PATIENT,
) -> tuple[TriageSession, str]:
    """
    Create a new triage session and return it with the framing message.

    Returns (session, framing_message).
    """
    session = TriageSession(
        id=uuid.uuid4(),
        status=SessionStatus.CONSENT_FRAMING.value,
        channel=channel,
        language=language.value,
        mode=mode.value,
        engine_version=settings.engine_version,
    )
    db.add(session)

    # Create an empty facts record for this session
    facts = SessionFact(session_id=session.id)
    db.add(facts)

    await db.flush()

    if mode == SessionMode.DOCTOR:
        framing_message = DOCTOR_FRAMING_MESSAGES.get(language, DOCTOR_FRAMING_MESSAGES[Language.EN])
    else:
        framing_message = FRAMING_MESSAGES.get(language, FRAMING_MESSAGES[Language.EN])
        
    return session, framing_message


async def update_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    language: Language | None = None,
    mode: SessionMode | None = None,
) -> tuple[TriageSession, str | None]:
    """
    Update the session's language and/or mode.
    Returns the updated session and an optional new framing message if the mode/language changed.
    """
    session = await get_session(db, session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    new_framing_message = None
    changed = False

    if language and language.value != session.language:
        session.language = language.value
        changed = True
    
    if mode and mode.value != session.mode:
        session.mode = mode.value
        changed = True

    if changed:
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()

        current_lang = Language(session.language)
        if session.mode == SessionMode.DOCTOR.value:
            new_framing_message = DOCTOR_FRAMING_MESSAGES.get(current_lang, DOCTOR_FRAMING_MESSAGES[Language.EN])
        else:
            new_framing_message = FRAMING_MESSAGES.get(current_lang, FRAMING_MESSAGES[Language.EN])

    return session, new_framing_message


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> TriageSession | None:
    """Retrieve a session by ID, or None if not found."""
    result = await db.execute(
        select(TriageSession).where(TriageSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def update_session_status(
    db: AsyncSession,
    session: TriageSession,
    new_status: SessionStatus,
) -> None:
    """
    Transition session to a new status with guard checks.

    Raises ValueError if the transition is invalid.
    """
    current = SessionStatus(session.status)
    valid_targets = _VALID_TRANSITIONS.get(current, set())

    if new_status not in valid_targets:
        raise ValueError(
            f"Invalid state transition: {current.value} → {new_status.value}"
        )

    session.status = new_status.value
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def close_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    reason: str | None = None,
) -> TriageSession:
    """
    Close / abandon a session explicitly (FR-05.4).

    Raises ValueError if session not found.
    """
    session = await get_session(db, session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    current = SessionStatus(session.status)
    # Terminal states cannot be re-closed
    if current in {SessionStatus.COMPLETED, SessionStatus.ESCALATED, SessionStatus.ABANDONED}:
        return session

    session.status = SessionStatus.ABANDONED.value
    session.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """
    Delete a session and all its related data (messages, facts, etc.) from the database.
    Returns True if deleted, False if not found.
    """
    session = await get_session(db, session_id)
    if session is None:
        return False
        
    # Explicitly delete related records to prevent SQLAlchemy from trying to set foreign keys to NULL
    await db.execute(delete(SessionFact).where(SessionFact.session_id == session_id))
    await db.execute(delete(Message).where(Message.session_id == session_id))
    await db.execute(delete(RuleEvent).where(RuleEvent.session_id == session_id))
    await db.execute(delete(ModelAudit).where(ModelAudit.session_id == session_id))
    
    await db.delete(session)
    await db.flush()
    return True


async def get_session_facts(db: AsyncSession, session_id: uuid.UUID) -> ExtractedFacts:
    """Load the current extracted facts for a session."""
    result = await db.execute(
        select(SessionFact).where(SessionFact.session_id == session_id)
    )
    fact_row = result.scalar_one_or_none()
    if fact_row is None:
        return ExtractedFacts()

    # Parse associated_symptoms from JSON string
    associated = []
    denied = []
    if fact_row.associated_symptoms:
        try:
            parsed = json.loads(fact_row.associated_symptoms)
            if isinstance(parsed, dict):
                associated = parsed.get("positive", [])
                denied = parsed.get("denied", [])
            elif isinstance(parsed, list):
                associated = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse extended facts (v2 fields)
    extended = {}
    if fact_row.extended_facts_json:
        try:
            extended = json.loads(fact_row.extended_facts_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return ExtractedFacts(
        chief_complaint=fact_row.chief_complaint,
        body_region=fact_row.body_region,
        duration=fact_row.duration,
        severity=fact_row.severity,
        associated_symptoms=associated,
        denied_symptoms=denied,
        age=fact_row.age,
        sex=fact_row.sex,
        is_pregnant=fact_row.is_pregnant,
        additional_context=fact_row.additional_context,
        medications=extended.get("medications", []),
        medical_history=extended.get("medical_history", []),
        allergies=extended.get("allergies", []),
        lifestyle_factors=extended.get("lifestyle_factors", []),
    )


async def save_session_facts(
    db: AsyncSession,
    session_id: uuid.UUID,
    facts: ExtractedFacts,
) -> None:
    """Persist extracted facts to the database."""
    result = await db.execute(
        select(SessionFact).where(SessionFact.session_id == session_id)
    )
    fact_row = result.scalar_one_or_none()
    if fact_row is None:
        fact_row = SessionFact(session_id=session_id)
        db.add(fact_row)

    fact_row.chief_complaint = facts.chief_complaint
    fact_row.body_region = facts.body_region
    fact_row.duration = facts.duration
    fact_row.severity = facts.severity
    
    if facts.associated_symptoms or facts.denied_symptoms:
        payload = {
            "positive": facts.associated_symptoms,
            "denied": facts.denied_symptoms,
        }
        fact_row.associated_symptoms = json.dumps(payload)
    else:
        fact_row.associated_symptoms = None

    fact_row.age = facts.age
    fact_row.sex = facts.sex
    fact_row.is_pregnant = facts.is_pregnant
    fact_row.additional_context = facts.additional_context

    # Persist extended facts (v2)
    extended_payload: dict = {}
    if facts.medications:
        extended_payload["medications"] = facts.medications
    if facts.medical_history:
        extended_payload["medical_history"] = facts.medical_history
    if facts.allergies:
        extended_payload["allergies"] = facts.allergies
    if facts.lifestyle_factors:
        extended_payload["lifestyle_factors"] = facts.lifestyle_factors
    fact_row.extended_facts_json = json.dumps(extended_payload) if extended_payload else None

    await db.flush()


def get_turn_count(session: TriageSession) -> int:
    """Get the number of user turns in the session."""
    if not session.messages:
        return 0
    return sum(1 for m in session.messages if m.role == "user")


async def save_recommendation_outcome(
    db: AsyncSession,
    session_id: uuid.UUID,
    specialty: str,
    urgency: Urgency,
    confidence: float,
) -> None:
    """
    Persist the final triage recommendation outcome to the session facts record.

    Called when the engine completes a triage session with a specialty recommendation.
    """
    result = await db.execute(
        select(SessionFact).where(SessionFact.session_id == session_id)
    )
    fact_row = result.scalar_one_or_none()
    if fact_row is None:
        fact_row = SessionFact(session_id=session_id)
        db.add(fact_row)

    fact_row.specialty = specialty
    fact_row.urgency = urgency.value
    fact_row.confidence = confidence
    await db.flush()
