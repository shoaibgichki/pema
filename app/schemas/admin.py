"""Pydantic schemas for admin API responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import Language, SessionStatus, Urgency
from app.schemas.fact import ExtractedFacts


class MessageDetail(BaseModel):
    """A single message in the session history."""

    role: str
    message_text: str
    turn_number: int
    timestamp: datetime

    model_config = {"from_attributes": True}


class RuleEventDetail(BaseModel):
    """A triggered safety rule event for admin review."""

    rule_name: str
    severity: str
    evidence_snippet: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class ModelAuditDetail(BaseModel):
    """LLM call audit record for admin review."""

    prompt_version: str
    model_name: str
    structured_output_json: dict | None = None
    clinical_reasoning: str | None = None  # Extracted from structured_output for easy reading
    latency_ms: int | None = None
    trace_id: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class SessionSummary(BaseModel):
    """Summary of a session for admin listing."""

    id: UUID
    status: SessionStatus
    language: Language
    channel: str
    specialty: str | None = None
    urgency: Urgency | None = None
    turn_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    """Full session detail with all related data for admin inspection."""

    id: UUID
    status: SessionStatus
    language: Language
    channel: str
    engine_version: str
    created_at: datetime
    updated_at: datetime
    extracted_facts: ExtractedFacts | None = None
    specialty: str | None = None
    urgency: Urgency | None = None
    messages: list[MessageDetail] = Field(default_factory=list)
    rule_events: list[RuleEventDetail] = Field(default_factory=list)
    model_audits: list[ModelAuditDetail] = Field(default_factory=list)
