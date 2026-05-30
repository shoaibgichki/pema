"""TriageSession ORM model (PRD §6.1 — triage_sessions table)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TriageSession(Base):
    """Master record for a triage session."""

    __tablename__ = "triage_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="consent_framing"
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="web"
    )
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, default="en"
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="patient"
    )
    engine_version: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    has_expressed_sympathy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Relationships
    messages = relationship("Message", back_populates="session", lazy="selectin")
    facts = relationship("SessionFact", back_populates="session", uselist=False, lazy="selectin")
    rule_events = relationship("RuleEvent", back_populates="session", lazy="selectin")
    model_audits = relationship("ModelAudit", back_populates="session", lazy="selectin")
