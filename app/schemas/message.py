"""Pydantic schemas for message API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import SessionStatus, Urgency
from app.schemas.fact import ExtractedFacts


# ── Requests ──────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    """Request body for POST /sessions/{id}/messages."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's message text",
    )


# ── Sub-models ────────────────────────────────────────────────────────────

class RuleEventResponse(BaseModel):
    """A triggered safety rule event returned in the message response."""

    rule_id: str
    rule_name: str
    severity: str
    evidence_snippet: str

    model_config = {"from_attributes": True}


# ── Responses ─────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Response for a processed user message."""

    session_id: UUID
    session_status: SessionStatus
    system_message: str
    extracted_facts: ExtractedFacts | None = None
    triggered_rules: list[RuleEventResponse] = Field(default_factory=list)
    specialty: str | None = None
    urgency: Urgency | None = None
    turn_number: int
