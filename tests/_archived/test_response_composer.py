"""
Response composer tests.

Tests follow-up question generation and recommendation composition
with mocked LLM calls and stub fallbacks.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.engine.llm_client import LLMCallMetadata
from app.engine.response_composer import (
    compose_follow_up,
    compose_recommendation,
    _urgency_text,
)
from app.schemas.enums import Language, Specialty, Urgency
from app.schemas.fact import ExtractedFacts


class TestUrgencyText:
    """Tests for urgency level text generation."""

    def test_english_routine(self):
        text = _urgency_text(Urgency.ROUTINE, Language.EN)
        assert "convenience" in text.lower()

    def test_english_urgent(self):
        text = _urgency_text(Urgency.URGENT, Language.EN)
        assert "24 hours" in text

    def test_urdu_routine(self):
        text = _urgency_text(Urgency.ROUTINE, Language.UR)
        assert "suvidha" in text.lower() or "appointment" in text.lower()

    def test_urdu_urgent(self):
        text = _urgency_text(Urgency.URGENT, Language.UR)
        assert "24" in text


class TestComposeFollowUpStub:
    """Tests for follow-up question generation WITHOUT LLM (stub mode)."""

    @pytest.mark.asyncio
    async def test_stub_english_chief_complaint(self):
        text, metadata = await compose_follow_up(
            conversation_history=[],
            facts=ExtractedFacts(),
            missing_facts=["chief_complaint", "age"],
            language=Language.EN,
        )
        assert metadata is None  # No LLM call
        assert len(text) > 0
        assert "bothering" in text.lower() or "tell me" in text.lower()

    @pytest.mark.asyncio
    async def test_stub_english_age(self):
        text, _ = await compose_follow_up(
            conversation_history=[],
            facts=ExtractedFacts(chief_complaint="headache"),
            missing_facts=["age", "sex"],
            language=Language.EN,
        )
        assert "age" in text.lower()

    @pytest.mark.asyncio
    async def test_stub_urdu_chief_complaint(self):
        text, _ = await compose_follow_up(
            conversation_history=[],
            facts=ExtractedFacts(),
            missing_facts=["chief_complaint"],
            language=Language.UR,
        )
        assert "takleef" in text.lower()

    @pytest.mark.asyncio
    async def test_stub_urdu_severity(self):
        text, _ = await compose_follow_up(
            conversation_history=[],
            facts=ExtractedFacts(chief_complaint="dard"),
            missing_facts=["severity"],
            language=Language.UR,
        )
        assert "shadeed" in text.lower() or "halki" in text.lower()


class TestComposeFollowUpLLM:
    """Tests for follow-up question generation WITH mocked LLM."""

    @pytest.mark.asyncio
    async def test_llm_follow_up(self):
        mock_metadata = LLMCallMetadata(
            prompt_version="v1",
            model_name="gpt-4o",
            latency_ms=300,
            trace_id="test-trace",
            raw_output={"text": "How long have you been having this headache?"},
        )

        with patch(
            "app.engine.response_composer.call_text",
            new_callable=AsyncMock,
            return_value=("How long have you been having this headache?", mock_metadata),
        ), patch("app.engine.response_composer.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.response_composition_prompt_version = "v1"

            text, metadata = await compose_follow_up(
                conversation_history=[],
                facts=ExtractedFacts(chief_complaint="headache"),
                missing_facts=["duration", "severity"],
                language=Language.EN,
            )

            assert "headache" in text
            assert metadata is not None
            assert metadata.latency_ms == 300

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_stub(self):
        with patch(
            "app.engine.response_composer.call_text",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ), patch("app.engine.response_composer.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.response_composition_prompt_version = "v1"

            text, metadata = await compose_follow_up(
                conversation_history=[],
                facts=ExtractedFacts(),
                missing_facts=["chief_complaint"],
                language=Language.EN,
            )

            # Should fall back to stub, no metadata
            assert len(text) > 0
            assert metadata is None


class TestComposeRecommendationStub:
    """Tests for recommendation generation WITHOUT LLM (stub mode)."""

    @pytest.mark.asyncio
    async def test_stub_english_recommendation(self):
        text, metadata = await compose_recommendation(
            conversation_history=[],
            facts=ExtractedFacts(chief_complaint="headache"),
            specialty=Specialty.NEUROLOGIST,
            urgency=Urgency.ROUTINE,
            language=Language.EN,
        )
        assert metadata is None
        assert "Neurologist" in text or "neurologist" in text
        assert "guidance" in text.lower()

    @pytest.mark.asyncio
    async def test_stub_urdu_recommendation(self):
        text, _ = await compose_recommendation(
            conversation_history=[],
            facts=ExtractedFacts(chief_complaint="pet dard"),
            specialty=Specialty.GASTROENTEROLOGIST,
            urgency=Urgency.URGENT,
            language=Language.UR,
        )
        assert "doctor" in text.lower()
        assert "rahnumai" in text.lower() or "guidance" in text.lower()

    @pytest.mark.asyncio
    async def test_stub_includes_urgency(self):
        text, _ = await compose_recommendation(
            conversation_history=[],
            facts=ExtractedFacts(chief_complaint="rash"),
            specialty=Specialty.DERMATOLOGIST,
            urgency=Urgency.ROUTINE,
            language=Language.EN,
        )
        assert "convenience" in text.lower()


class TestComposeRecommendationLLM:
    """Tests for recommendation generation WITH mocked LLM."""

    @pytest.mark.asyncio
    async def test_llm_recommendation(self):
        llm_response = (
            "Based on your symptoms, I'd recommend seeing a Neurologist. "
            "You can schedule an appointment at your convenience. "
            "Remember, this is guidance only."
        )
        mock_metadata = LLMCallMetadata(
            prompt_version="v1",
            model_name="gpt-4o",
            latency_ms=500,
            trace_id="test-trace-rec",
            raw_output={"text": llm_response},
        )

        with patch(
            "app.engine.response_composer.call_text",
            new_callable=AsyncMock,
            return_value=(llm_response, mock_metadata),
        ), patch("app.engine.response_composer.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.response_composition_prompt_version = "v1"

            text, metadata = await compose_recommendation(
                conversation_history=[],
                facts=ExtractedFacts(chief_complaint="headache", age=30),
                specialty=Specialty.NEUROLOGIST,
                urgency=Urgency.ROUTINE,
                language=Language.EN,
            )

            assert "Neurologist" in text
            assert metadata is not None
            assert metadata.latency_ms == 500
