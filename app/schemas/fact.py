"""Pydantic schema for extracted clinical facts."""

from pydantic import BaseModel, Field


class ExtractedFacts(BaseModel):
    """
    Structured representation of clinical facts extracted from the conversation.

    This schema serves as:
    - The structured output target for the AI Conversation Engine
    - The in-memory representation during triage processing
    - The shape stored in the session_facts DB table

    Fields are nullable because facts are gathered incrementally across turns.
    """

    chief_complaint: str | None = Field(
        None, description="Primary symptom or concern in the user's words"
    )
    body_region: str | None = Field(
        None, description="Affected body region (e.g., chest, head, abdomen)"
    )
    duration: str | None = Field(
        None, description="How long the symptom has been present (e.g., '3 days', '1 week')"
    )
    severity: str | None = Field(
        None, description="Symptom severity: mild, moderate, or severe"
    )
    associated_symptoms: list[str] = Field(
        default_factory=list,
        description="Other symptoms the user has mentioned",
    )
    denied_symptoms: list[str] = Field(
        default_factory=list,
        description="Symptoms the user explicitly denied having",
    )
    age: int | None = Field(None, description="Patient age in years")
    sex: str | None = Field(
        None, description="Patient sex: male or female"
    )
    is_pregnant: bool | None = Field(
        None, description="Whether the patient is pregnant (asked for females of reproductive age)"
    )
    additional_context: str | None = Field(
        None,
        description="Any other relevant information the user provided",
    )

    # Extended fields for AI-driven context (new in v2)
    medications: list[str] = Field(
        default_factory=list,
        description="Current medications the patient is taking",
    )
    medical_history: list[str] = Field(
        default_factory=list,
        description="Relevant known medical conditions or past diagnoses",
    )
    allergies: list[str] = Field(
        default_factory=list,
        description="Known allergies mentioned by the patient",
    )
    lifestyle_factors: list[str] = Field(
        default_factory=list,
        description="Relevant lifestyle factors (e.g., smoking, diet, exercise, stress)",
    )

    def merge(self, new_facts: "ExtractedFacts") -> "ExtractedFacts":
        """
        Merge newly extracted facts into existing facts.

        New non-None values override existing ones. Lists are extended (deduped).
        Existing non-None values are never erased.
        """
        merged = {}
        list_fields = {
            "associated_symptoms", "denied_symptoms",
            "medications", "medical_history", "allergies", "lifestyle_factors",
        }
        for field_name in self.model_fields:
            existing = getattr(self, field_name)
            new_val = getattr(new_facts, field_name)

            if field_name in list_fields:
                # Extend the list, dedup while preserving order
                combined = list(dict.fromkeys((existing or []) + (new_val or [])))
                merged[field_name] = combined
            elif new_val is not None:
                merged[field_name] = new_val
            else:
                merged[field_name] = existing

        return ExtractedFacts(**merged)
