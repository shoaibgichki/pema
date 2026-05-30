"""
Admin API routes (PRD §7, FR-07.3).

Endpoints for internal reviewers to inspect sessions, decision paths, and audit data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.message import Message
from app.models.model_audit import ModelAudit
from app.models.rule_event import RuleEvent
from app.models.session import TriageSession
from app.models.fact import SessionFact
from app.schemas.admin import (
    MessageDetail,
    ModelAuditDetail,
    RuleEventDetail,
    SessionDetail,
    SessionSummary,
)
from app.schemas.enums import SessionStatus
from app.schemas.fact import ExtractedFacts

import json

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/sessions",
    response_model=list[SessionSummary],
    summary="List recent sessions (admin)",
)
async def list_sessions(
    status_filter: SessionStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SessionSummary]:
    """List sessions with optional filtering for admin review."""
    stmt = select(TriageSession).order_by(TriageSession.created_at.desc())

    if status_filter is not None:
        stmt = stmt.where(TriageSession.status == status_filter.value)

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    summaries = []
    for s in sessions:
        turn_count = sum(1 for m in s.messages if m.role == "user") if s.messages else 0

        # Get specialty/urgency from facts if available
        specialty = None
        urgency = None
        if s.facts:
            specialty = s.facts.specialty
            urgency = s.facts.urgency

        summaries.append(
            SessionSummary(
                id=s.id,
                status=SessionStatus(s.status),
                language=s.language,
                channel=s.channel,
                specialty=specialty,
                urgency=urgency,
                turn_count=turn_count,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
        )

    return summaries


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetail,
    summary="Inspect a session in full detail (admin)",
)
async def get_session_detail(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """
    Full session detail including messages, rule events, and model audits.

    Provides enough data to fully reconstruct the decision path (FR-07.2).
    """
    result = await db.execute(
        select(TriageSession)
        .where(TriageSession.id == session_id)
        .options(
            selectinload(TriageSession.messages),
            selectinload(TriageSession.rule_events),
            selectinload(TriageSession.model_audits),
            selectinload(TriageSession.facts),
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Build extracted facts
    extracted_facts = None
    specialty = None
    urgency = None
    if session.facts:
        associated = []
        denied = []
        if session.facts.associated_symptoms:
            try:
                parsed = json.loads(session.facts.associated_symptoms)
                if isinstance(parsed, dict):
                    associated = parsed.get("positive", [])
                    denied = parsed.get("denied", [])
                elif isinstance(parsed, list):
                    associated = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse extended facts (v2)
        extended = {}
        if hasattr(session.facts, 'extended_facts_json') and session.facts.extended_facts_json:
            try:
                import json as _json
                extended = _json.loads(session.facts.extended_facts_json)
            except Exception:
                pass

        extracted_facts = ExtractedFacts(
            chief_complaint=session.facts.chief_complaint,
            body_region=session.facts.body_region,
            duration=session.facts.duration,
            severity=session.facts.severity,
            associated_symptoms=associated,
            denied_symptoms=denied,
            age=session.facts.age,
            sex=session.facts.sex,
            is_pregnant=session.facts.is_pregnant,
            additional_context=session.facts.additional_context,
            medications=extended.get("medications", []),
            medical_history=extended.get("medical_history", []),
            allergies=extended.get("allergies", []),
            lifestyle_factors=extended.get("lifestyle_factors", []),
        )
        specialty = session.facts.specialty
        urgency = session.facts.urgency

    # Build message list
    messages = sorted(session.messages, key=lambda m: m.turn_number)
    message_details = [
        MessageDetail(
            role=m.role,
            message_text=m.message_text,
            turn_number=m.turn_number,
            timestamp=m.timestamp,
        )
        for m in messages
    ]

    # Build rule event list
    rule_details = [
        RuleEventDetail(
            rule_name=r.rule_name,
            severity=r.severity,
            evidence_snippet=r.evidence_snippet,
            timestamp=r.timestamp,
        )
        for r in session.rule_events
    ]

    # Build model audit list — extract clinical_reasoning from conversation engine outputs
    audit_details = [
        ModelAuditDetail(
            prompt_version=a.prompt_version,
            model_name=a.model_name,
            structured_output_json=a.structured_output_json,
            clinical_reasoning=(
                a.structured_output_json.get("clinical_reasoning")
                if a.structured_output_json and isinstance(a.structured_output_json, dict)
                else None
            ),
            latency_ms=a.latency_ms,
            trace_id=a.trace_id,
            timestamp=a.timestamp,
        )
        for a in session.model_audits
    ]

    return SessionDetail(
        id=session.id,
        status=SessionStatus(session.status),
        language=session.language,
        channel=session.channel,
        engine_version=session.engine_version,
        created_at=session.created_at,
        updated_at=session.updated_at,
        extracted_facts=extracted_facts,
        specialty=specialty,
        urgency=urgency,
        messages=message_details,
        rule_events=rule_details,
        model_audits=audit_details,
    )
