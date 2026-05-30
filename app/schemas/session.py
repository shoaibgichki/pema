"""Pydantic schemas for session API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import Language, SessionStatus, Urgency, SessionMode
from app.schemas.fact import ExtractedFacts


# ── Requests ──────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """Request body for POST /sessions."""

    language: Language = Field(
        Language.EN,
        description="Preferred language for the session (en or ur)",
    )
    mode: SessionMode = Field(
        SessionMode.PATIENT,
        description="Behavioral mode of the assistant (patient or doctor)",
    )

class UpdateSessionRequest(BaseModel):
    """Request body for PATCH /sessions/{id}."""

    language: Language | None = None
    mode: SessionMode | None = None


class CloseSessionRequest(BaseModel):
    """Request body for POST /sessions/{id}/close."""

    reason: str | None = Field(
        None, description="Optional reason for closing the session"
    )


# ── Responses ─────────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    """Response for session creation and retrieval."""

    id: UUID
    status: SessionStatus
    language: Language
    mode: SessionMode
    created_at: datetime
    updated_at: datetime
    engine_version: str
    has_expressed_sympathy: bool = False
    framing_message: str | None = None
    extracted_facts: ExtractedFacts | None = None
    specialty: str | None = None
    urgency: Urgency | None = None

    model_config = {"from_attributes": True}


class SessionCloseResponse(BaseModel):
    """Confirmation response for session closure."""

    id: UUID
    status: SessionStatus
    closed_at: datetime
