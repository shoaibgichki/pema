"""SessionFact ORM model (PRD §6.1 — session_facts table)."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SessionFact(Base):
    """Structured extracted facts for a triage session — one row per session."""

    __tablename__ = "session_facts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("triage_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Extracted clinical facts
    chief_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    associated_symptoms: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="JSON-encoded list of symptoms"
    )
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_pregnant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    additional_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON blob for extended AI-captured context (v2): medications, medical_history,
    # allergies, lifestyle_factors. Stored as JSON string for schema flexibility.
    extended_facts_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome (populated on completion)
    urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    session = relationship("TriageSession", back_populates="facts")
