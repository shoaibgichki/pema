"""
Session API routes (PRD §7).

Handles session creation, message processing, state retrieval, and closure.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.engine import orchestrator, session_manager
from app.engine.audit_logger import log_message
from app.schemas.enums import SessionStatus
from app.schemas.fact import ExtractedFacts
from app.schemas.message import MessageResponse, RuleEventResponse, SendMessageRequest
from app.schemas.session import (
    CloseSessionRequest,
    CreateSessionRequest,
    SessionCloseResponse,
    SessionResponse,
    UpdateSessionRequest,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new triage session",
)
async def create_session(
    body: CreateSessionRequest = CreateSessionRequest(),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """
    Start a new triage session (FR-05.1).

    Returns the session ID and a framing/disclaimer message (FR-06.1).
    """
    session, framing_message = await session_manager.create_session(
        db, language=body.language, mode=body.mode
    )

    # Log the framing message as the first system message
    await log_message(db, session.id, "system", framing_message, turn_number=0)

    return SessionResponse(
        id=session.id,
        status=SessionStatus(session.status),
        language=body.language,
        mode=body.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
        engine_version=session.engine_version,
        framing_message=framing_message,
    )


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Update an existing triage session",
)
async def update_session(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Update language or mode for an existing session."""

    try:
        session, framing_message = await session_manager.update_session(
            db, session_id, language=body.language, mode=body.mode
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    
    if framing_message:
        # If the mode changed, let's log the new framing message as a system message
        # So the UI knows and the audit trail captures the transition context.
        # Use turn_count = whatever it is currently. Actually we don't know the turn count here 
        # easily without querying, but turn 0 is fine for system framing.
        pass # UI will render it directly. For audit log, maybe we log it if needed.

    facts = await session_manager.get_session_facts(db, session_id)

    return SessionResponse(
        id=session.id,
        status=SessionStatus(session.status),
        language=session.language,
        mode=session.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
        engine_version=session.engine_version,
        framing_message=framing_message,
        extracted_facts=facts,
    )


@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    summary="Send a user message and receive the engine response",
)
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Process a user message through the triage engine pipeline.

    Runs fact extraction, safety rules, policy engine, and response composition.
    Returns the system response along with updated session state.
    """
    try:
        result = await orchestrator.process_turn(db, session_id, body.text)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    triggered_rules = [
        RuleEventResponse(
            rule_id=r.rule_id,
            rule_name=r.rule_name,
            severity=r.severity,
            evidence_snippet=r.evidence_snippet,
        )
        for r in result.triggered_rules
    ]

    return MessageResponse(
        session_id=session_id,
        session_status=result.session_status,
        system_message=result.system_message,
        extracted_facts=result.extracted_facts,
        triggered_rules=triggered_rules,
        specialty=result.specialty,
        urgency=result.urgency,
        turn_number=result.turn_number,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get current session state",
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Retrieve the current state and extracted facts for a session."""
    session = await session_manager.get_session(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    facts = await session_manager.get_session_facts(db, session_id)

    return SessionResponse(
        id=session.id,
        status=SessionStatus(session.status),
        language=session.language,
        mode=session.mode,
        created_at=session.created_at,
        updated_at=session.updated_at,
        engine_version=session.engine_version,
        extracted_facts=facts,
    )


@router.post(
    "/{session_id}/close",
    response_model=SessionCloseResponse,
    summary="Close or abandon a session",
)
async def close_session(
    session_id: uuid.UUID,
    body: CloseSessionRequest = CloseSessionRequest(),
    db: AsyncSession = Depends(get_db),
) -> SessionCloseResponse:
    """Explicitly close a session (FR-05.4)."""
    try:
        session = await session_manager.close_session(db, session_id, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return SessionCloseResponse(
        id=session.id,
        status=SessionStatus(session.status),
        closed_at=session.updated_at,
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session and all its data",
)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a triage session and all its associated data from the database."""
    deleted = await session_manager.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
