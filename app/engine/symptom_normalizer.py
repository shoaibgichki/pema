"""
Symptom normalizer — LLM-based pre-pass for safety rule matching.

Converts colloquial and Roman Urdu symptom descriptions into canonical
clinical English terminology so that the deterministic safety rules can
match semantically equivalent phrases.

ARCHITECTURE NOTE:
- This module does NOT make safety decisions.
- It only translates/normalizes input text.
- The deterministic safety_rules engine makes all decisions.
- If this module fails, the safety pipeline falls back to raw text.
- False negatives in normalization are safe — raw text is always checked too.
"""

from __future__ import annotations

import asyncio
import logging

from app.engine.llm_client import LLMCallMetadata, call_text
from app.prompts.symptom_normalization import (
    SYMPTOM_NORMALIZATION_PROMPT_VERSION,
    SYMPTOM_NORMALIZATION_SYSTEM_PROMPT,
    SYMPTOM_NORMALIZATION_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Timeout for the normalization call in seconds.
# If exceeded, we fall back to the raw user text immediately.
NORMALIZATION_TIMEOUT_SECONDS = 20.0


async def normalize_for_safety(
    raw_text: str,
) -> tuple[str, LLMCallMetadata | None]:
    """
    Normalize user text into canonical clinical terminology for safety rule matching.

    Calls the LLM to rewrite colloquial or Roman Urdu symptom descriptions
    into standard English clinical terms that the keyword-based safety rules
    can reliably match.

    This function:
    1. Sends the raw user message to the LLM with a normalization prompt
    2. Returns the normalized clinical text for use in safety rule matching
    3. Degrades gracefully — returns (raw_text, None) on any failure

    Args:
        raw_text: The original user message, in any language or phrasing.

    Returns:
        Tuple of (normalized_text, LLMCallMetadata | None).
        - normalized_text: Canonical clinical terms (or raw_text on failure).
        - metadata: LLM call audit data, or None if the call was skipped/failed.

    Safety guarantee:
        This function NEVER raises an exception. Any error results in
        returning the original raw_text, ensuring the safety pipeline
        always has something to check.
    """
    if not raw_text or not raw_text.strip():
        return raw_text, None

    user_prompt = SYMPTOM_NORMALIZATION_USER_TEMPLATE.format(
        user_message=raw_text.strip()
    )

    try:
        normalized_text, metadata = await asyncio.wait_for(
            call_text(
                system_prompt=SYMPTOM_NORMALIZATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                prompt_version=SYMPTOM_NORMALIZATION_PROMPT_VERSION,
                temperature=0.0,  # Maximum determinism for safety-critical step
            ),
            timeout=NORMALIZATION_TIMEOUT_SECONDS,
        )

        normalized_text = normalized_text.strip()

        # Sanity check: if the normalizer returns something suspiciously short
        # or empty, fall back to raw text
        if not normalized_text or len(normalized_text) < 3:
            logger.warning(
                "Symptom normalizer returned empty/too-short result, using raw text. "
                "Raw: %r, Normalized: %r",
                raw_text[:100],
                normalized_text,
            )
            return raw_text, metadata

        logger.debug(
            "Symptom normalization completed in %dms: %r → %r",
            metadata.latency_ms,
            raw_text[:80],
            normalized_text[:80],
        )

        return normalized_text, metadata

    except asyncio.TimeoutError:
        logger.warning(
            "Symptom normalization timed out after %.1fs, using raw text for safety check",
            NORMALIZATION_TIMEOUT_SECONDS,
        )
        return raw_text, None

    except Exception as e:  # noqa: BLE001
        logger.error(
            "Symptom normalization failed (%s: %s), falling back to raw text",
            type(e).__name__,
            e,
        )
        return raw_text, None