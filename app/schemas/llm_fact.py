"""
LLM-compatible schema for structured fact extraction.

This module provides a schema variant that is compatible with OpenAI's
strict JSON Schema mode, which requires all fields to be required and
uses explicit null types instead of Optional.
"""

from pydantic import BaseModel, Field


class LLMExtractedFacts(BaseModel):
    """
    Structured output schema for the LLM fact extractor.

    All fields are required with null defaults for JSON Schema strict mode.
    The LLM will populate values it can extract and leave others as null.
    """

    chief_complaint: str | None = Field(
        None, description="Primary symptom or concern in the patient's own words"
    )
    body_region: str | None = Field(
        None, description="Affected body region (e.g., chest, head, abdomen, back, skin)"
    )
    duration: str | None = Field(
        None, description="How long the symptom has been present (e.g., '3 days', '1 week')"
    )
    severity: str | None = Field(
        None, description="Symptom severity: mild, moderate, or severe"
    )
    associated_symptoms: list[str] | None = Field(
        default_factory=list,
        description="List of other symptoms mentioned, in short English medical terms",
    )
    denied_symptoms: list[str] | None = Field(
        default_factory=list,
        description="List of symptoms explicitly denied by the patient, in short English medical terms",
    )
    age: int | None = Field(
        None, description="Patient age in years"
    )
    sex: str | None = Field(
        None, description="Patient sex: male or female"
    )
    is_pregnant: bool | None = Field(
        None, description="Whether the patient is pregnant, if mentioned"
    )
    additional_context: str | None = Field(
        None, description="Any other relevant details the patient mentioned"
    )
    detected_language: str | None = Field(
        None,
        description="Language of the user's message: 'en' for English, 'ur' for Roman Urdu, 'mixed' for code-switching",
    )
