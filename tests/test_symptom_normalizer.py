"""
Symptom normalizer unit tests.

Tests for the LLM-based symptom normalization pre-pass, including:
- Graceful degradation when LLM is unavailable
- Timeout fallback behaviour
- Mock-based normalization output tests
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.engine.symptom_normalizer import (
    NORMALIZATION_TIMEOUT_SECONDS,
    normalize_for_safety,
)
from app.engine.llm_client import LLMCallMetadata


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_metadata(text: str = "chest pain") -> LLMCallMetadata:
    """Build a minimal LLMCallMetadata for mock returns."""
    return LLMCallMetadata(
        prompt_version="symptom_norm_v1",
        model_name="gpt-4o",
        latency_ms=120,
        trace_id="test-trace-001",
        raw_output={"text": text},
    )


# ── Graceful Degradation ──────────────────────────────────────────────────


class TestGracefulDegradation:
    """Normalizer must never block the safety pipeline."""

    @pytest.mark.asyncio
    async def test_returns_raw_text_on_llm_exception(self):
        """If the LLM call raises, raw text is returned with no exception bubbling."""
        with patch(
            "app.engine.symptom_normalizer.call_text",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            result_text, metadata = await normalize_for_safety("heart pain")
        assert result_text == "heart pain"
        assert metadata is None

    @pytest.mark.asyncio
    async def test_returns_raw_text_on_timeout(self):
        """If the LLM call times out, raw text is returned immediately."""

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(NORMALIZATION_TIMEOUT_SECONDS + 1)
            return ("chest pain", _make_metadata())

        with patch("app.engine.symptom_normalizer.call_text", side_effect=slow_call):
            result_text, metadata = await normalize_for_safety("heart pain")
        assert result_text == "heart pain"
        assert metadata is None

    @pytest.mark.asyncio
    async def test_returns_raw_text_on_empty_normalizer_output(self):
        """If the LLM returns an empty string, fall back to raw text."""
        with patch(
            "app.engine.symptom_normalizer.call_text",
            return_value=("", _make_metadata("")),
        ):
            result_text, metadata = await normalize_for_safety("heart pain")
        assert result_text == "heart pain"
        # Metadata is still returned (LLM call happened, output was just empty)
        assert metadata is not None

    @pytest.mark.asyncio
    async def test_empty_input_returns_immediately(self):
        """Empty or whitespace-only input skips the LLM call entirely."""
        with patch(
            "app.engine.symptom_normalizer.call_text"
        ) as mock_call:
            result_text, metadata = await normalize_for_safety("   ")
        mock_call.assert_not_called()
        assert result_text == "   "
        assert metadata is None

    @pytest.mark.asyncio
    async def test_never_raises(self):
        """normalize_for_safety must never propagate an exception to the caller."""
        with patch(
            "app.engine.symptom_normalizer.call_text",
            side_effect=Exception("unexpected catastrophic failure"),
        ):
            try:
                await normalize_for_safety("I feel terrible")
            except Exception as exc:
                pytest.fail(f"normalize_for_safety raised an exception: {exc}")


# ── Successful Normalization ──────────────────────────────────────────────


class TestSuccessfulNormalization:
    """Tests for expected normalization output when the LLM is available."""

    @pytest.mark.asyncio
    async def test_returns_normalized_text_and_metadata(self):
        """On success, returns the normalized string and LLM metadata."""
        mock_meta = _make_metadata("chest pain, difficulty breathing")
        with patch(
            "app.engine.symptom_normalizer.call_text",
            return_value=("chest pain, difficulty breathing", mock_meta),
        ):
            result_text, metadata = await normalize_for_safety("heart pain")

        assert result_text == "chest pain, difficulty breathing"
        assert metadata is not None
        assert metadata.prompt_version == "symptom_norm_v1"
        assert metadata.latency_ms == 120

    @pytest.mark.asyncio
    async def test_whitespace_stripped_from_output(self):
        """Leading/trailing whitespace in LLM output is stripped."""
        mock_meta = _make_metadata("  chest pain  ")
        with patch(
            "app.engine.symptom_normalizer.call_text",
            return_value=("  chest pain, shortness of breath  ", mock_meta),
        ):
            result_text, _ = await normalize_for_safety("heart pain")

        assert result_text == "chest pain, shortness of breath"
        assert not result_text.startswith(" ")
        assert not result_text.endswith(" ")

    @pytest.mark.asyncio
    async def test_uses_temperature_zero(self):
        """Normalization call must use temperature=0.0 for maximum determinism."""
        captured_kwargs: dict = {}

        async def capture_call(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return ("chest pain", _make_metadata())

        with patch("app.engine.symptom_normalizer.call_text", side_effect=capture_call):
            await normalize_for_safety("heart pain")

        assert captured_kwargs.get("temperature") == 0.0

    @pytest.mark.asyncio
    async def test_uses_correct_prompt_version(self):
        """Normalization call uses the expected prompt version constant."""
        captured_kwargs: dict = {}

        async def capture_call(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return ("chest pain", _make_metadata())

        with patch("app.engine.symptom_normalizer.call_text", side_effect=capture_call):
            await normalize_for_safety("heart pain")

        assert captured_kwargs.get("prompt_version") == "symptom_norm_v1"


# ── Integration with Safety Rules ────────────────────────────────────────


class TestIntegrationWithSafetyRules:
    """
    End-to-end integration tests: normalization output → safety rule matching.

    These tests use a real (mocked LLM) normalization result piped directly
    into check_safety_rules to verify the full detection chain.
    """

    @pytest.mark.asyncio
    async def test_heart_pain_normalized_catches_rf001(self):
        """Full chain: 'heart pain' → normalize → 'chest pain, ...' → RF-001 fires."""
        from app.engine.safety_rules import check_safety_rules, has_emergency

        mock_meta = _make_metadata("chest pain, difficulty breathing, shortness of breath")
        with patch(
            "app.engine.symptom_normalizer.call_text",
            return_value=(
                "chest pain, difficulty breathing, shortness of breath",
                mock_meta,
            ),
        ):
            normalized, _ = await normalize_for_safety("heart pain breathing problem")

        matches = check_safety_rules(
            raw_text="heart pain breathing problem",
            normalized_text=normalized,
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    @pytest.mark.asyncio
    async def test_indirect_suicidal_phrase_caught_via_full_chain(self):
        """'I see no point in living' → normalize → suicidal ideation terms → RF-004 fires."""
        from app.engine.safety_rules import check_safety_rules, has_emergency

        raw = "I see no point in living anymore"
        normalized_output = "suicidal ideation, no reason to live, want to end life"
        mock_meta = _make_metadata(normalized_output)

        with patch(
            "app.engine.symptom_normalizer.call_text",
            return_value=(normalized_output, mock_meta),
        ):
            normalized, _ = await normalize_for_safety(raw)

        matches = check_safety_rules(raw_text=raw, normalized_text=normalized)
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-004" for m in matches)

    @pytest.mark.asyncio
    async def test_fallback_raw_matching_still_works_on_llm_failure(self):
        """If the normalizer fails, RF-001 still catches 'chest pain' in raw text."""
        from app.engine.safety_rules import check_safety_rules, has_emergency

        with patch(
            "app.engine.symptom_normalizer.call_text",
            side_effect=RuntimeError("LLM down"),
        ):
            normalized, _ = await normalize_for_safety(
                "chest pain and shortness of breath"
            )

        # normalized == raw_text (fallback)
        matches = check_safety_rules(
            raw_text="chest pain and shortness of breath",
            normalized_text=normalized,
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)
