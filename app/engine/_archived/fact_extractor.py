"""
Fact extractor — LLM-based extraction of structured clinical facts (PRD FR-01).

Converts free-text patient messages into validated ExtractedFacts using
the OpenAI Responses API with structured output.

This module is the ONLY LLM integration point for fact extraction.
The LLM does NOT make decisions — it only extracts and structures data.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.engine.llm_client import LLMCallMetadata, call_structured
from app.prompts.fact_extraction import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_USER_TEMPLATE,
)
from app.schemas.fact import ExtractedFacts
from app.schemas.llm_fact import LLMExtractedFacts

if TYPE_CHECKING:
    from app.models.message import Message

logger = logging.getLogger(__name__)


def _format_conversation_history(messages: list[Message]) -> str:
    """Format conversation messages for the prompt context."""
    if not messages:
        return "(No previous messages)"

    lines = []
    for msg in messages:
        role_label = "PATIENT" if msg.role == "user" else "SYSTEM"
        lines.append(f"{role_label}: {msg.message_text}")
    return "\n".join(lines)


def _format_previous_facts(facts: ExtractedFacts) -> str:
    """Format currently known facts as a readable block for the prompt."""
    fact_dict = facts.model_dump(exclude_none=True, exclude_defaults=True)
    if not fact_dict:
        return "(No facts known yet)"

    lines = []
    for key, value in fact_dict.items():
        if isinstance(value, list):
            if value:
                lines.append(f"- {key}: {', '.join(str(v) for v in value)}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "(No facts known yet)"


def _llm_facts_to_extracted(llm_facts: LLMExtractedFacts) -> ExtractedFacts:
    """Convert LLM schema output to the internal ExtractedFacts schema."""
    return ExtractedFacts(
        chief_complaint=llm_facts.chief_complaint,
        body_region=llm_facts.body_region,
        duration=llm_facts.duration,
        severity=llm_facts.severity,
        associated_symptoms=llm_facts.associated_symptoms or [],
        denied_symptoms=llm_facts.denied_symptoms or [],
        age=llm_facts.age,
        sex=llm_facts.sex,
        is_pregnant=llm_facts.is_pregnant,
        additional_context=llm_facts.additional_context,
    )


async def extract_facts(
    conversation_history: list[Message],
    current_facts: ExtractedFacts,
    new_message: str,
) -> tuple[ExtractedFacts, str | None, LLMCallMetadata]:
    """
    Extract structured facts from a new user message using the LLM.

    This function:
    1. Builds the prompt with conversation context + known facts
    2. Calls the LLM with structured output (JSON schema enforcement)
    3. Validates the response against the Pydantic schema
    4. Merges new facts with existing facts (new values override, never erase)
    5. Returns updated facts, detected language, and audit metadata

    Args:
        conversation_history: All messages in the session so far.
        current_facts: Currently known facts from previous turns.
        new_message: The new user message to extract facts from.

    Returns:
        Tuple of (merged ExtractedFacts, detected_language, LLMCallMetadata).
    """
    # Derive last system message from history
    last_system_message = "(None)"
    for msg in reversed(conversation_history):
        if msg.role == "system":
            last_system_message = msg.message_text
            break

    # Build prompts
    user_prompt = FACT_EXTRACTION_USER_TEMPLATE.format(
        previous_facts=_format_previous_facts(current_facts),
        conversation_history=_format_conversation_history(conversation_history),
        last_system_message=last_system_message,
        new_message=new_message,
    )

    try:
        llm_facts, metadata = await call_structured(
            system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=LLMExtractedFacts,
            prompt_version=settings.fact_extraction_prompt_version,
            temperature=0.1,  # Low temperature for accurate extraction
        )

        # Convert to internal schema
        new_facts = _llm_facts_to_extracted(llm_facts)

        # Merge: new non-null values override existing; never erase
        merged_facts = current_facts.merge(new_facts)

        # Detect language
        detected_language = llm_facts.detected_language

        logger.info(
            "Fact extraction completed in %dms (trace: %s)",
            metadata.latency_ms,
            metadata.trace_id,
        )

        return merged_facts, detected_language, metadata

    except Exception as e:
        logger.error("Fact extraction failed: %s", str(e), exc_info=True)
        # On failure, return current facts unchanged with error metadata
        error_metadata = LLMCallMetadata(
            prompt_version=settings.fact_extraction_prompt_version,
            model_name=settings.openai_model,
            latency_ms=0,
            trace_id="error",
            raw_output={"error": str(e)},
        )
        return current_facts, None, error_metadata
