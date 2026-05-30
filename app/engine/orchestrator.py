"""
Orchestrator — main turn-processing pipeline (v2).

This is the central coordinator invoked on each user message.
Pipeline: safety check (parallel with AI) → emergency override → AI turn → save.

v2 changes vs v1:
  - The middle section (fact extraction + policy engine + response composer)
    has been replaced by a single AI Conversation Engine call.
  - The AI now drives the conversation: it decides what to ask, extracts facts,
    and determines when to recommend and which specialty/urgency to suggest.
  - Emergency detection is unchanged — deterministic, runs before the AI.
  - The sympathy-tracking flag is removed (the AI handles tone naturally).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.engine import audit_logger, session_manager
from app.engine.conversation_engine import run_turn
from app.engine.safety_rules import SafetyRuleMatch, check_safety_rules, has_emergency
from app.engine.symptom_normalizer import normalize_for_safety
from app.schemas.enums import Language, SessionStatus, Urgency, SessionMode
from app.schemas.fact import ExtractedFacts

logger = logging.getLogger(__name__)


# ── Emergency Response Templates (deterministic, not LLM) ─────────────────

EMERGENCY_TEMPLATES = {
    Language.EN: (
        "🚨 EMERGENCY ALERT 🚨\n"
        "{reason}\n\n"
        "❌ Do NOT continue chatting with me.\n"
        "✅ Call 1122 IMMEDIATELY or go to the nearest hospital emergency room.\n\n"
        "If someone is with you, inform them right away. Do not delay."
    ),
    Language.UR: (
        "🚨 EMERGENCY ALERT 🚨\n"
        "{reason}\n\n"
        "❌ Is waqt mujhse baat mat karein.\n"
        "✅ ABHI 1122 call karein ya qareeb ke hospital ke emergency mein jayein.\n\n"
        "Agar koi sath hai to unhe bhi batayein. Waqt zaya na karein."
    ),
}

EMERGENCY_REASONS = {
    Language.EN: {
        "RF-001": "Chest pain with breathing difficulty can be a sign of a heart attack or other life-threatening condition.",
        "RF-002": "Severe or uncontrolled bleeding requires immediate medical attention.",
        "RF-003": "Loss of consciousness could indicate a serious medical condition.",
        "RF-004": "I hear that you're going through a very difficult time. You are not alone. Please reach out for help immediately.",
        "RF-005": "These could be signs of a stroke. Every minute matters.",
        "RF-006": "These could be signs of a severe allergic reaction (anaphylaxis). This can be life-threatening.",
        "RF-007": "Severe abdominal pain with fever and vomiting needs urgent medical evaluation.",
        "RF-008": "High fever in a young child can be dangerous and needs immediate medical attention.",
        "RF-009": "Seizures require immediate medical attention.",
        "RF-010": "Bleeding or severe pain during pregnancy requires immediate emergency care.",
        "RF-011": "A sudden, extremely severe headache can be a sign of a life-threatening condition.",
    },
    Language.UR: {
        "RF-001": "Seenay mein dard aur saans ki takleef bohat serious ho sakti hai.",
        "RF-002": "Shadeed ya beqaabu khoon behna fori medical madad ki zaroorat hai.",
        "RF-003": "Behoshi kisi sangin medical maslay ki nishani ho sakti hai.",
        "RF-004": "Main samajhta hoon ke aap bohat mushkil waqt se guzar rahe hain. Aap akele nahi hain. Fori madad le lein.",
        "RF-005": "Yeh stroke ki nishan ho sakti hain. Har minute ahem hai.",
        "RF-006": "Yeh shadeed allergic reaction (anaphylaxis) ki nishan ho sakti hain. Yeh jaan lewa ho sakta hai.",
        "RF-007": "Shadeed pet dard bukhar aur ulti ke sath fori medical jaanch zaruri hai.",
        "RF-008": "Chhote bachon mein tez bukhar khatarnak ho sakta hai aur fori medical tawajjo chahiye.",
        "RF-009": "Dore/mirgi ke liye fori medical tawajjo chahiye.",
        "RF-010": "Hamal mein khoon ya shadeed dard ke liye fori emergency care zaruri hai.",
        "RF-011": "Achanak, bohat shadeed sar dard kisi khatarnak bimari ki nishani ho sakta hai.",
    },
}


# ── Orchestrator Result ───────────────────────────────────────────────────


class TurnResult:
    """Result of processing a single user turn."""

    def __init__(
        self,
        system_message: str,
        session_status: SessionStatus,
        extracted_facts: ExtractedFacts,
        triggered_rules: list[SafetyRuleMatch],
        turn_number: int,
        specialty: str | None = None,
        urgency: str | None = None,
        clinical_reasoning: str | None = None,
    ):
        self.system_message = system_message
        self.session_status = session_status
        self.extracted_facts = extracted_facts
        self.triggered_rules = triggered_rules
        self.turn_number = turn_number
        self.specialty = specialty
        self.urgency = urgency
        self.clinical_reasoning = clinical_reasoning


# ── Main Pipeline ─────────────────────────────────────────────────────────


async def process_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_text: str,
) -> TurnResult:
    """
    Process a single user turn through the full engine pipeline (v2).

    Pipeline steps:
    1. Load session + facts
    2. Save user message
    3. Handle early state transitions
    4. Run symptom normalization (parallel, for safety matching)
    5. Run safety rules (deterministic, on every turn)
    6. If emergency → hard override: escalate, skip AI, return
    7. Run AI Conversation Engine (single LLM call: reason + respond)
    8. Save facts, messages, audit trail
    9. Handle recommendation if AI provided one → complete session
    10. Return result
    """
    # 1. Load session & current facts
    session = await session_manager.get_session(db, session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    current_status = SessionStatus(session.status)
    if current_status in {SessionStatus.COMPLETED, SessionStatus.ESCALATED, SessionStatus.ABANDONED}:
        raise ValueError(f"Session {session_id} is in terminal state: {current_status.value}")

    facts = await session_manager.get_session_facts(db, session_id)
    language = Language(session.language)
    turn_count = session_manager.get_turn_count(session) + 1

    # 2. Save user message
    user_msg = await audit_logger.log_message(db, session_id, "user", user_text, turn_count)

    # 3. Handle early state transitions
    if current_status == SessionStatus.CONSENT_FRAMING:
        await session_manager.update_session_status(db, session, SessionStatus.CHIEF_COMPLAINT)
        current_status = SessionStatus.CHIEF_COMPLAINT
    if current_status == SessionStatus.CHIEF_COMPLAINT:
        await session_manager.update_session_status(db, session, SessionStatus.FACT_GATHERING)
        current_status = SessionStatus.FACT_GATHERING

    # 4. Build raw conversation history (for safety rules multi-turn detection)
    user_messages = [
        msg.message_text for msg in (session.messages or []) if msg.role == "user"
    ]
    user_messages.append(user_text)
    raw_history = " ".join(user_messages)

    # 5. Run symptom normalization (parallel safety pre-pass)
    normalized_text: str = user_text  # fallback: always use raw text
    norm_metadata = None

    if settings.openai_api_key:
        try:
            normalized_text, norm_metadata = await normalize_for_safety(user_text)
        except Exception as e:
            logger.warning("Symptom normalization failed, using raw text: %s", e)

        if norm_metadata:
            await audit_logger.log_model_audit(
                db,
                session_id=session_id,
                prompt_version=norm_metadata.prompt_version,
                model_name=norm_metadata.model_name,
                structured_output={
                    "raw_text": user_text,
                    "normalized_text": normalized_text,
                },
                latency_ms=norm_metadata.latency_ms,
                trace_id=norm_metadata.trace_id,
            )

    # 6. Run safety rules (deterministic, runs on EVERY turn — FR-03.1)
    rule_matches = check_safety_rules(raw_history, facts, normalized_text)

    # 7. HARD OVERRIDE: If emergency, escalate immediately (FR-03.3)
    #    The AI never sees this message. Emergency handling is fully deterministic.
    #    Bypass this hard override in Doctor Mode, as the AI should handle it clinically.
    if has_emergency(rule_matches) and session.mode != SessionMode.DOCTOR.value:
        await session_manager.update_session_status(db, session, SessionStatus.ESCALATED)
        await audit_logger.log_rule_events(db, session_id, rule_matches)

        system_message = _compose_emergency_response(rule_matches, language)
        await audit_logger.log_message(db, session_id, "system", system_message, turn_count)

        return TurnResult(
            system_message=system_message,
            session_status=SessionStatus.ESCALATED,
            extracted_facts=facts,
            triggered_rules=rule_matches,
            turn_number=turn_count,
            specialty="emergency_department",
            urgency="emergency",
            clinical_reasoning="[Emergency escalation — deterministic safety override]",
        )

    # Log any urgent (non-emergency) rule matches
    if rule_matches:
        await audit_logger.log_rule_events(db, session_id, rule_matches)

    # 8. AI Conversation Engine — single LLM call that does everything
    current_messages = list(session.messages or [])
    current_messages.append(user_msg)
    
    ai_output, ai_metadata = await run_turn(
        conversation_history=current_messages,
        turn_count=turn_count,
        language=language.value,
        mode=session.mode,
    )

    # Update language if AI detected a switch
    if ai_output.detected_language in ("en", "ur"):
        if ai_output.detected_language != session.language:
            session.language = ai_output.detected_language
            language = Language(ai_output.detected_language)

    # Merge AI-extracted facts with existing session facts
    merged_facts = facts.merge(ai_output.extracted_facts)

    # 9. Log AI turn audit (includes clinical_reasoning in structured_output_json)
    if ai_metadata:
        await audit_logger.log_model_audit(
            db,
            session_id=session_id,
            prompt_version=ai_metadata.prompt_version,
            model_name=ai_metadata.model_name,
            structured_output=ai_metadata.raw_output,
            latency_ms=ai_metadata.latency_ms,
            trace_id=ai_metadata.trace_id,
        )

    # 10. Save system response message
    system_message = ai_output.message
    await audit_logger.log_message(db, session_id, "system", system_message, turn_count)

    # 11. Save updated facts
    await session_manager.save_session_facts(db, session_id, merged_facts)

    # 12. Handle recommendation — complete the session if AI provided one
    final_specialty = None
    final_urgency = None
    if ai_output.recommendation:
        rec = ai_output.recommendation
        final_specialty = rec.specialty
        final_urgency = rec.urgency.value

        # Transition to SPECIALTY_ROUTING → COMPLETED
        if SessionStatus(session.status) == SessionStatus.FACT_GATHERING:
            await session_manager.update_session_status(
                db, session, SessionStatus.SPECIALTY_ROUTING
            )
        await session_manager.save_recommendation_outcome(
            db, session_id, rec.specialty, rec.urgency, rec.confidence
        )
        await session_manager.update_session_status(db, session, SessionStatus.COMPLETED)
        current_status = SessionStatus.COMPLETED

    return TurnResult(
        system_message=system_message,
        session_status=current_status,
        extracted_facts=merged_facts,
        triggered_rules=rule_matches,
        turn_number=turn_count,
        specialty=final_specialty,
        urgency=final_urgency,
        clinical_reasoning=ai_output.clinical_reasoning,
    )


def _compose_emergency_response(
    matches: list[SafetyRuleMatch],
    language: Language,
) -> str:
    """Build the emergency response from deterministic templates (not LLM)."""
    template = EMERGENCY_TEMPLATES.get(language, EMERGENCY_TEMPLATES[Language.EN])
    reasons_map = EMERGENCY_REASONS.get(language, EMERGENCY_REASONS[Language.EN])

    primary_match = matches[0]
    reason = reasons_map.get(primary_match.rule_id, primary_match.rule_name)

    response = template.format(reason=reason)

    # Append crisis info if present (e.g., RF-004 suicidal ideation)
    for match in matches:
        if match.crisis_info:
            response += f"\n\n{match.crisis_info}"
            break

    return response
