"""
Audit logger — persists full trace data for every turn (FR-07).

Stores raw input, extracted facts, triggered rules, LLM call metadata,
and final system response to enable full decision-path reconstruction (FR-07.2).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.model_audit import ModelAudit
from app.models.rule_event import RuleEvent
from app.engine.safety_rules import SafetyRuleMatch


async def log_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    text: str,
    turn_number: int,
) -> Message:
    """Persist a message to the conversation history."""
    msg = Message(
        session_id=session_id,
        role=role,
        message_text=text,
        turn_number=turn_number,
    )
    db.add(msg)
    await db.flush()
    return msg


async def log_rule_events(
    db: AsyncSession,
    session_id: uuid.UUID,
    matches: list[SafetyRuleMatch],
) -> list[RuleEvent]:
    """Persist triggered safety rule events."""
    events = []
    for match in matches:
        event = RuleEvent(
            session_id=session_id,
            rule_name=f"{match.rule_id}: {match.rule_name}",
            severity=match.severity,
            evidence_snippet=match.evidence_snippet,
        )
        db.add(event)
        events.append(event)

    if events:
        await db.flush()
    return events


async def log_model_audit(
    db: AsyncSession,
    session_id: uuid.UUID,
    prompt_version: str,
    model_name: str,
    structured_output: dict | None = None,
    latency_ms: int | None = None,
    trace_id: str | None = None,
) -> ModelAudit:
    """Persist an LLM call audit record."""
    audit = ModelAudit(
        session_id=session_id,
        prompt_version=prompt_version,
        model_name=model_name,
        structured_output_json=structured_output,
        latency_ms=latency_ms,
        trace_id=trace_id or str(uuid.uuid4()),
    )
    db.add(audit)
    await db.flush()
    return audit


async def log_normalization(
    db: AsyncSession,
    session_id: uuid.UUID,
    raw_text: str,
    normalized_text: str,
    latency_ms: int | None,
    model_name: str,
    trace_id: str | None = None,
) -> ModelAudit:
    """
    Persist a symptom normalization audit record.

    Records the original user text alongside the LLM-produced normalized
    clinical text so that administrators can trace whether normalization
    contributed to a red-flag detection (FR-07.2).
    """
    return await log_model_audit(
        db,
        session_id=session_id,
        prompt_version="symptom_norm_v1",
        model_name=model_name,
        structured_output={
            "raw_text": raw_text,
            "normalized_text": normalized_text,
        },
        latency_ms=latency_ms,
        trace_id=trace_id,
    )
