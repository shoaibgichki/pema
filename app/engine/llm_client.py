"""
Async LLM client for PEMA (v2).

Thin wrapper around the OpenAI Python SDK using the Chat Completions API
with structured output (JSON mode + Pydantic schema).

Compatible with any OpenAI-compatible provider (OpenAI, OpenRouter, etc.)
via the `openai_base_url` config setting.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import TypeVar, Type

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings


# ── Audit Metadata ────────────────────────────────────────────────────────


@dataclass
class LLMCallMetadata:
    """Metadata captured from an LLM call for audit logging."""

    prompt_version: str
    model_name: str
    latency_ms: int
    trace_id: str
    raw_output: dict | None = None


# ── Client Singleton ──────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Get or create the async OpenAI client."""
    global _client
    if _client is None:
        kwargs: dict = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        _client = AsyncOpenAI(**kwargs)
    return _client


def reset_client() -> None:
    """Reset the cached client (useful after config changes in tests)."""
    global _client
    _client = None


# ── Structured Output Call ────────────────────────────────────────────────

T = TypeVar("T", bound=BaseModel)


async def call_structured(
    system_prompt: str,
    user_prompt: str,
    response_schema: Type[T],
    prompt_version: str,
    model: str | None = None,
    temperature: float = 0.1,
    extra_messages: list[dict] | None = None,
) -> tuple[T, LLMCallMetadata]:
    """
    Make a structured-output LLM call using the Chat Completions API.

    Uses JSON mode with the Pydantic schema included in the system prompt
    to extract structured data. Compatible with OpenAI, OpenRouter, and
    any OpenAI-compatible provider.

    Args:
        system_prompt: The system instruction.
        user_prompt: A simple user-facing prompt (can be empty when extra_messages
                     provides the full conversation context).
        response_schema: A Pydantic model class defining the expected output.
        prompt_version: Version string for audit trail.
        model: Model override (defaults to settings.openai_model).
        temperature: Sampling temperature (low for extraction).
        extra_messages: Optional pre-built messages list (used by the conversation
                        engine to pass the full conversation history). When provided,
                        user_prompt is ignored.

    Returns:
        Tuple of (parsed Pydantic object, call metadata).
    """
    client = _get_client()
    model_name = model or settings.openai_model
    trace_id = str(uuid.uuid4())
    start = time.monotonic()

    # Build schema instruction for the system prompt
    schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
    system_with_schema = (
        f"{system_prompt}\n\n"
        f"You MUST respond with valid JSON that conforms to this schema:\n"
        f"```json\n{schema_json}\n```\n"
        f"Respond ONLY with the JSON object. No markdown, no explanation."
    )

    # Build messages array
    if extra_messages:
        # Conversation engine path: use pre-built history messages
        messages = [
            {"role": "system", "content": system_with_schema},
            *extra_messages,
        ]
    else:
        # Simple call path (e.g., normalization)
        messages = [
            {"role": "system", "content": system_with_schema},
            {"role": "user", "content": user_prompt},
        ]

    response = await client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Extract the text content from the response
    raw_text = response.choices[0].message.content

    # Parse into Pydantic model
    parsed = response_schema.model_validate_json(raw_text)

    metadata = LLMCallMetadata(
        prompt_version=prompt_version,
        model_name=model_name,
        latency_ms=elapsed_ms,
        trace_id=trace_id,
        raw_output=parsed.model_dump(),
    )

    return parsed, metadata


async def call_text(
    system_prompt: str,
    user_prompt: str,
    prompt_version: str,
    model: str | None = None,
    temperature: float = 0.7,
) -> tuple[str, LLMCallMetadata]:
    """
    Make a plain text LLM call using the Chat Completions API.

    Used for symptom normalization (safety pre-pass).

    Args:
        system_prompt: The system instruction.
        user_prompt: The user-facing prompt content.
        prompt_version: Version string for audit trail.
        model: Model override (defaults to settings.openai_model).
        temperature: Sampling temperature.

    Returns:
        Tuple of (text response, call metadata).
    """
    client = _get_client()
    model_name = model or settings.openai_model
    trace_id = str(uuid.uuid4())
    start = time.monotonic()

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    text = response.choices[0].message.content

    metadata = LLMCallMetadata(
        prompt_version=prompt_version,
        model_name=model_name,
        latency_ms=elapsed_ms,
        trace_id=trace_id,
        raw_output={"text": text},
    )

    return text, metadata
