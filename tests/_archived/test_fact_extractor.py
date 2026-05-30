"""
Fact extractor tests.

Tests the fact extraction module with mocked LLM calls.
Also tests the LLM fact schema and fact merging via the extractor.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.engine.fact_extractor import (
    extract_facts,
    _format_conversation_history,
    _format_previous_facts,
    _llm_facts_to_extracted,
)
from app.engine.llm_client import LLMCallMetadata
from app.schemas.fact import ExtractedFacts
from app.schemas.llm_fact import LLMExtractedFacts


class TestFormatHelpers:
    """Tests for prompt formatting helpers."""

    def test_format_empty_conversation(self):
        result = _format_conversation_history([])
        assert "No previous messages" in result

    def test_format_previous_facts_empty(self):
        facts = ExtractedFacts()
        result = _format_previous_facts(facts)
        assert "No facts known yet" in result

    def test_format_previous_facts_with_data(self):
        facts = ExtractedFacts(
            chief_complaint="headache",
            age=30,
            associated_symptoms=["nausea"],
        )
        result = _format_previous_facts(facts)
        assert "headache" in result
        assert "30" in result
        assert "nausea" in result

    def test_format_previous_facts_empty_list(self):
        facts = ExtractedFacts(associated_symptoms=[])
        result = _format_previous_facts(facts)
        assert "No facts known yet" in result


class TestLLMFactsConversion:
    """Tests for LLM schema to internal schema conversion."""

    def test_basic_conversion(self):
        llm_facts = LLMExtractedFacts(
            chief_complaint="stomach pain",
            body_region="abdomen",
            duration="3 days",
            severity="moderate",
            associated_symptoms=["nausea", "bloating"],
            age=32,
            sex="male",
            is_pregnant=None,
            additional_context=None,
            detected_language="en",
        )
        result = _llm_facts_to_extracted(llm_facts)
        assert result.chief_complaint == "stomach pain"
        assert result.body_region == "abdomen"
        assert result.age == 32
        assert result.sex == "male"
        assert "nausea" in result.associated_symptoms
        assert "bloating" in result.associated_symptoms

    def test_null_fields_preserved(self):
        llm_facts = LLMExtractedFacts(
            chief_complaint="fever",
            detected_language="ur",
        )
        result = _llm_facts_to_extracted(llm_facts)
        assert result.chief_complaint == "fever"
        assert result.age is None
        assert result.sex is None
        assert result.duration is None


class TestFactExtraction:
    """Tests for the extract_facts function with mocked LLM."""

    @pytest.mark.asyncio
    async def test_extract_facts_with_mock(self):
        """Test that extract_facts correctly calls LLM and merges results."""
        mock_llm_result = LLMExtractedFacts(
            chief_complaint="stomach pain",
            body_region="abdomen",
            duration="3 days",
            severity="moderate",
            associated_symptoms=["nausea"],
            age=32,
            sex="male",
            is_pregnant=None,
            additional_context=None,
            detected_language="en",
        )
        mock_metadata = LLMCallMetadata(
            prompt_version="v1",
            model_name="gpt-4o",
            latency_ms=500,
            trace_id="test-trace-1",
            raw_output=mock_llm_result.model_dump(),
        )

        with patch(
            "app.engine.fact_extractor.call_structured",
            new_callable=AsyncMock,
            return_value=(mock_llm_result, mock_metadata),
        ):
            current_facts = ExtractedFacts()
            facts, lang, metadata = await extract_facts(
                conversation_history=[],
                current_facts=current_facts,
                new_message="I have stomach pain for 3 days, age 32 male",
            )

            assert facts.chief_complaint == "stomach pain"
            assert facts.age == 32
            assert facts.sex == "male"
            assert facts.duration == "3 days"
            assert lang == "en"
            assert metadata.latency_ms == 500

    @pytest.mark.asyncio
    async def test_extract_facts_merges_with_existing(self):
        """Test that new facts merge with (not replace) existing facts."""
        mock_llm_result = LLMExtractedFacts(
            chief_complaint=None,  # Not mentioned again
            severity="severe",
            associated_symptoms=["vomiting"],
            detected_language="en",
        )
        mock_metadata = LLMCallMetadata(
            prompt_version="v1",
            model_name="gpt-4o",
            latency_ms=400,
            trace_id="test-trace-2",
        )

        with patch(
            "app.engine.fact_extractor.call_structured",
            new_callable=AsyncMock,
            return_value=(mock_llm_result, mock_metadata),
        ):
            current_facts = ExtractedFacts(
                chief_complaint="headache",
                age=25,
                associated_symptoms=["nausea"],
            )
            facts, lang, _ = await extract_facts(
                conversation_history=[],
                current_facts=current_facts,
                new_message="it's getting worse and I'm vomiting now",
            )

            # Existing facts preserved
            assert facts.chief_complaint == "headache"
            assert facts.age == 25
            # New facts merged
            assert facts.severity == "severe"
            assert "nausea" in facts.associated_symptoms
            assert "vomiting" in facts.associated_symptoms

    @pytest.mark.asyncio
    async def test_extract_facts_roman_urdu(self):
        """Test Roman Urdu input fact extraction."""
        mock_llm_result = LLMExtractedFacts(
            chief_complaint="bukhar aur sar dard",
            body_region="head",
            associated_symptoms=["fever", "headache"],
            detected_language="ur",
        )
        mock_metadata = LLMCallMetadata(
            prompt_version="v1",
            model_name="gpt-4o",
            latency_ms=450,
            trace_id="test-trace-3",
        )

        with patch(
            "app.engine.fact_extractor.call_structured",
            new_callable=AsyncMock,
            return_value=(mock_llm_result, mock_metadata),
        ):
            facts, lang, _ = await extract_facts(
                conversation_history=[],
                current_facts=ExtractedFacts(),
                new_message="mujhe bukhar hai aur sar dard ho raha hai",
            )

            assert facts.chief_complaint == "bukhar aur sar dard"
            assert lang == "ur"
            assert "fever" in facts.associated_symptoms
            assert "headache" in facts.associated_symptoms

    @pytest.mark.asyncio
    async def test_extract_facts_handles_llm_error(self):
        """Test graceful fallback when LLM call fails."""
        with patch(
            "app.engine.fact_extractor.call_structured",
            new_callable=AsyncMock,
            side_effect=Exception("API rate limit"),
        ):
            current_facts = ExtractedFacts(chief_complaint="headache")
            facts, lang, metadata = await extract_facts(
                conversation_history=[],
                current_facts=current_facts,
                new_message="it's getting worse",
            )

            # Original facts preserved on error
            assert facts.chief_complaint == "headache"
            assert lang is None
            assert metadata.trace_id == "error"
            assert "API rate limit" in metadata.raw_output["error"]


class TestLLMExtractedFactsSchema:
    """Tests to verify the LLM schema is valid for OpenAI structured output."""

    def test_schema_generates_valid_json_schema(self):
        schema = LLMExtractedFacts.model_json_schema()
        assert "properties" in schema
        assert "chief_complaint" in schema["properties"]
        assert "detected_language" in schema["properties"]

    def test_schema_all_fields_present(self):
        schema = LLMExtractedFacts.model_json_schema()
        expected_fields = [
            "chief_complaint", "body_region", "duration", "severity",
            "associated_symptoms", "age", "sex", "is_pregnant",
            "additional_context", "detected_language",
        ]
        for field in expected_fields:
            assert field in schema["properties"], f"Missing field: {field}"

    def test_schema_parses_minimal_json(self):
        """Test that the schema can parse a minimal JSON response."""
        minimal = LLMExtractedFacts.model_validate({
            "chief_complaint": "headache",
            "detected_language": "en",
        })
        assert minimal.chief_complaint == "headache"
        assert minimal.age is None

    def test_schema_parses_full_json(self):
        """Test that the schema can parse a complete JSON response."""
        full = LLMExtractedFacts.model_validate({
            "chief_complaint": "stomach pain",
            "body_region": "abdomen",
            "duration": "3 days",
            "severity": "moderate",
            "associated_symptoms": ["nausea", "bloating"],
            "age": 32,
            "sex": "male",
            "is_pregnant": None,
            "additional_context": "pain after eating",
            "detected_language": "en",
        })
        assert full.chief_complaint == "stomach pain"
        assert full.age == 32
        assert len(full.associated_symptoms) == 2
