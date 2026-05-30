"""
AI Conversation Engine — core triage reasoning module (v2).

This module replaces the three separate v1 modules:
  - fact_extractor.py      (structured fact extraction)
  - policy_engine.py       (what to ask next, specialty routing)
  - response_composer.py   (phrasing the response)

A single LLM call per turn gives the AI the full conversation history and
lets it reason holistically: extract facts, decide what to ask, phrase the
question naturally, and determine when it has enough information to recommend.

The AI uses its own training knowledge for clinical reasoning — medications,
symptom clusters, side effects, age-appropriate concerns, etc. No injected
databases or clinical references.

Emergency detection NEVER happens here — it is handled by the deterministic
safety_rules engine BEFORE this module is called. If this module is running,
the current turn has already been confirmed as non-emergency.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.engine.llm_client import LLMCallMetadata, call_structured
from app.prompts.conversation_system import (
    CONVERSATION_PROMPT_VERSION,
    CONVERSATION_SYSTEM_PROMPT,
)
from app.prompts.doctor_system import (
    DOCTOR_PROMPT_VERSION,
    DOCTOR_SYSTEM_PROMPT,
)
from app.schemas.conversation import ConversationTurnOutput
from app.schemas.enums import Urgency, SessionMode
from app.schemas.fact import ExtractedFacts

if TYPE_CHECKING:
    from app.models.message import Message

logger = logging.getLogger(__name__)


# ── Fallback (no API key configured) ─────────────────────────────────────


_FALLBACK_MESSAGE_EN = (
    "I'm having trouble connecting to the AI service right now. "
    "Please try again in a moment, or if your symptoms are urgent, "
    "please call 1122 or visit your nearest hospital."
)

_FALLBACK_MESSAGE_UR = (
    "Is waqt AI service se connection mein mushkil aa rahi hai. "
    "Thodi der baad dobara koshish karein. Agar takleef shadeed hai to "
    "1122 call karein ya qareeb ke hospital jayein."
)


def _build_messages(
    conversation_history: list[Message],
    schema_instruction: str,
) -> list[dict]:
    """
    Build the OpenAI messages array from conversation history.

    Maps:
      - system → prepend the PEMA system prompt (already in the call_structured wrapper)
      - user messages → role: "user"
      - system/assistant messages → role: "assistant"

    The schema instruction is appended to the last user message so the AI
    knows exactly what JSON structure to produce.
    """
    messages: list[dict] = []

    for msg in conversation_history:
        if msg.role == "user":
            messages.append({"role": "user", "content": msg.message_text})
        else:
            # "system" role messages from the DB are PEMA's previous responses
            messages.append({"role": "assistant", "content": msg.message_text})

    # Append schema instruction as a system-level reminder at the end
    if messages and messages[-1]["role"] == "user":
        # Attach schema reminder directly to the last user message
        messages[-1]["content"] += f"\n\n{schema_instruction}"
    else:
        # Safety fallback: add as a new user message
        messages.append({"role": "user", "content": schema_instruction})

    return messages


# ── Public API ────────────────────────────────────────────────────────────


async def run_turn(
    conversation_history: list[Message],
    turn_count: int,
    language: str = "en",
    mode: str = "patient",
) -> tuple[ConversationTurnOutput, LLMCallMetadata | None]:
    """
    Run one triage conversation turn through the AI.

    This is the single LLM call that replaces v1's fact_extractor +
    policy_engine + response_composer pipeline.

    The AI receives the full conversation history and system prompt and
    produces a structured response that includes:
    - The patient-facing message (next question or recommendation)
    - Updated extracted facts (merged from the full conversation)
    - An optional recommendation (when the AI has enough information)
    - Internal clinical reasoning (for admin audit trail)
    - Detected language

    Args:
        conversation_history: All messages in the session so far (DB objects).
        turn_count: Current turn number (used for logging and context).
        language: Current session language ('en' or 'ur') — passed as context hint.

    Returns:
        Tuple of (ConversationTurnOutput, LLMCallMetadata | None).
        Returns a fallback output if the API key is not configured.
    """
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key — returning fallback message")
        fallback_msg = _FALLBACK_MESSAGE_UR if language == "ur" else _FALLBACK_MESSAGE_EN
        fallback_output = ConversationTurnOutput(
            message=fallback_msg,
            extracted_facts=ExtractedFacts(),
            recommendation=None,
            clinical_reasoning="[No API key configured — fallback response returned]",
            detected_language=language,
        )
        return fallback_output, None

    try:
        lang_hint = "Roman Urdu" if language == "ur" else "English"

        # Build the schema-aware system prompt
        schema_json = json.dumps(
            ConversationTurnOutput.model_json_schema(), indent=2
        )
        schema_instruction = (
            f"[CURRENT TURN: {turn_count} | PATIENT LANGUAGE HINT: {lang_hint}]\n\n"
            f"Respond ONLY with valid JSON conforming to this schema:\n"
            f"```json\n{schema_json}\n```\n"
            f"No markdown, no explanation outside the JSON."
        )

        # Build conversation messages for the API call
        messages = _build_messages(conversation_history, schema_instruction)

        if mode == SessionMode.DOCTOR.value:
            system_prompt = DOCTOR_SYSTEM_PROMPT
            prompt_version = DOCTOR_PROMPT_VERSION
        else:
            system_prompt = CONVERSATION_SYSTEM_PROMPT
            prompt_version = CONVERSATION_PROMPT_VERSION

        # Make the structured LLM call
        output, metadata = await call_structured(
            system_prompt=system_prompt,
            user_prompt="",  # All content is in the messages array
            response_schema=ConversationTurnOutput,
            prompt_version=prompt_version,
            temperature=0.7,
            extra_messages=messages,
        )

        logger.info(
            "Conversation turn %d completed in %dms (lang=%s, has_recommendation=%s)",
            turn_count,
            metadata.latency_ms,
            output.detected_language,
            output.recommendation is not None,
        )

        return output, metadata

    except Exception as e:
        logger.error(
            "Conversation engine failed on turn %d: %s",
            turn_count,
            str(e),
            exc_info=True,
        )
        # Graceful fallback
        fallback_msg = _FALLBACK_MESSAGE_UR if language == "ur" else _FALLBACK_MESSAGE_EN
        fallback_output = ConversationTurnOutput(
            message=fallback_msg,
            extracted_facts=ExtractedFacts(),
            recommendation=None,
            clinical_reasoning=f"[Engine error: {type(e).__name__}: {e}]",
            detected_language=language,
        )
        return fallback_output, None
