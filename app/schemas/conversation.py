"""
Pydantic schemas for the AI Conversation Engine output (v2).

These schemas define the structured output the AI produces each turn.
The AI returns both the patient-facing message AND its internal clinical
reasoning and extracted facts in one call.
"""

from pydantic import BaseModel, Field

from app.schemas.enums import Urgency
from app.schemas.fact import ExtractedFacts


class TriageRecommendation(BaseModel):
    """
    The AI's recommendation when it has gathered enough information.

    Produced only when the AI decides it has a complete enough picture
    to recommend a doctor type. Not present in intermediate turns.
    """

    specialty: str = Field(
        description="The recommended doctor specialty (e.g. 'gastroenterologist', 'vascular_surgeon'). Do NOT route to emergency_department here."
    )
    urgency: Urgency = Field(
        description="How urgently the patient should seek care"
    )
    confidence: float = Field(
        description="AI confidence in this recommendation (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )
    rationale: str = Field(
        description=(
            "Internal rationale for this recommendation — why this specialty "
            "and urgency level. Used for audit and quality review. "
            "NOT shown to the patient."
        )
    )


class ConversationTurnOutput(BaseModel):
    """
    The full structured output from the AI Conversation Engine for a single turn.

    The AI returns this on every turn. It contains:
    - The patient-facing message
    - Updated clinical facts extracted from the conversation so far
    - An optional recommendation (only present when the AI is ready to conclude)
    - Internal clinical reasoning for audit and admin review
    - Detected language for language-matching
    """

    message: str = Field(
        description=(
            "The message to show the patient. A natural, empathetic follow-up "
            "question or, if a recommendation is present, the recommendation message "
            "including disclaimer."
        )
    )
    extracted_facts: ExtractedFacts = Field(
        description=(
            "All clinical facts extracted from the full conversation so far, "
            "including the current turn. Merges incrementally — facts are never erased."
        )
    )
    recommendation: TriageRecommendation | None = Field(
        default=None,
        description=(
            "Present only when the AI has gathered sufficient information to "
            "recommend a doctor type. None means the conversation should continue."
        ),
    )
    clinical_reasoning: str = Field(
        description=(
            "The AI's internal clinical reasoning for this turn. "
            "Explains what it understood from the patient, what it's trying "
            "to establish, and why it asked this particular question (or made "
            "this recommendation). Used for admin review and quality assurance. "
            "NEVER shown to the patient."
        )
    )
    detected_language: str = Field(
        default="en",
        description="Detected language: 'en' for English, 'ur' for Roman Urdu, 'mixed' for code-switching",
    )
