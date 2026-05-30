"""
Response composer — generates user-facing messages (PRD §5.2, FR-02).

Responsible for:
- Follow-up questions (LLM-generated, one at a time, plain language)
- Recommendation messages (LLM-generated, includes specialty + urgency + disclaimer)
- Emergency responses (deterministic templates, NOT LLM)

Only follow-up questions and recommendations use the LLM.
Emergency responses are hardcoded templates — never delegated to the LLM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.engine.llm_client import LLMCallMetadata, call_text
from app.prompts.response_composition import (
    FOLLOW_UP_SYSTEM_PROMPT,
    FOLLOW_UP_USER_TEMPLATE,
    RECOMMENDATION_SYSTEM_PROMPT,
    RECOMMENDATION_USER_TEMPLATE,
    SPECIALTY_PLAIN_NAMES,
)
from app.schemas.enums import Language, Specialty, Urgency
from app.schemas.fact import ExtractedFacts

if TYPE_CHECKING:
    from app.models.message import Message

logger = logging.getLogger(__name__)


# ── Stub Follow-Up Questions (fallback when LLM unavailable) ─────────────

_STUB_QUESTIONS = {
    Language.EN: {
        # Baseline facts
        "chief_complaint": "Tell me, what's bothering you today?",
        "age": "Can you tell me your age?",
        "sex": "Are you male or female?",
        "duration": "How long have you been experiencing this?",
        "severity": "How would you rate the severity — mild, moderate, or severe?",
        "is_pregnant": "Are you currently pregnant?",
        "associated_symptoms": "Have you noticed any other symptoms?",
        # CARDIAC pathway discriminators
        "shortness_of_breath": "Are you also having difficulty breathing or feeling short of breath?",
        "radiating_pain": "Does the pain spread to your arm, jaw, neck, or back?",
        "onset_type": "Did this come on suddenly or gradually?",
        # NEUROLOGICAL pathway discriminators
        "vision_changes": "Have you noticed any changes in your vision, like blurring or double vision?",
        "numbness_weakness": "Do you have any numbness or weakness, especially on one side of your body?",
        "headache_onset": "Did the headache come on suddenly and severely, or gradually?",
        # ABDOMINAL pathway discriminators
        "fever_present": "Do you also have a fever?",
        "vomiting_present": "Have you been vomiting or feeling very nauseous?",
        "pain_location": "Can you tell me exactly where in the abdomen the pain is?",
        # RESPIRATORY pathway discriminators
        "chest_tightness": "Does your chest feel tight or heavy when you breathe?",
        "blood_in_cough": "Have you noticed any blood when you cough?",
        # GYNECOLOGICAL pathway discriminators
        "pregnancy_status": "Is there any possibility you could be pregnant?",
        "bleeding_pattern": "Can you describe the bleeding — is it heavier, lighter, or spotting?",
        "pain_severity_location": "Where exactly is the pain — is it on one side or both sides?",
        # UROLOGICAL pathway discriminators
        "blood_in_urine": "Have you noticed any blood in your urine?",
        "flank_pain": "Do you have any pain in your side or back, below the ribs?",
        # MUSCULOSKELETAL pathway discriminators
        "injury_history": "Did this start after an injury or fall, or did it come on by itself?",
        "swelling_present": "Is there any swelling, redness, or warmth in the area?",
        "movement_limitation": "Are you able to move the affected area normally?",
        # MENTAL_HEALTH pathway discriminators
        "sleep_impact": "How has your sleep been — are you sleeping too little, too much, or having trouble sleeping?",
        "daily_function_impact": "How are these feelings affecting your day-to-day life?",
        "support_system": "Do you have family or friends you can lean on for support?",
    },
    Language.UR: {
        # Baseline facts
        "chief_complaint": "Batayein, kya takleef hai?",
        "age": "Aapki umar kya hai?",
        "sex": "Aap mard hain ya aurat?",
        "duration": "Yeh takleef kab se hai?",
        "severity": "Takleef kitni shadeed hai — halki, darmiyani, ya shadeed?",
        "is_pregnant": "Kya aap is waqt hamal se hain?",
        "associated_symptoms": "Kya aur koi takleef bhi hai?",
        # CARDIAC pathway discriminators
        "shortness_of_breath": "Kya aapko saans lene mein bhi mushkil ho rahi hai?",
        "radiating_pain": "Kya dard baazu, jabde, gardun, ya peeth ki taraf ja raha hai?",
        "onset_type": "Yeh achanak hua ya dheere dheere?",
        # NEUROLOGICAL pathway discriminators
        "vision_changes": "Kya aapki nazar mein koi farq hua hai, jaise dhundlana ya double nazar aana?",
        "numbness_weakness": "Kya jism ke kisi hisse mein sunnpan ya kamzori hai, khaaskar ek taraf?",
        "headache_onset": "Sar dard achanak aur shadeed tha ya dheere dheere?",
        # ABDOMINAL pathway discriminators
        "fever_present": "Kya bukhar bhi hai?",
        "vomiting_present": "Kya ulti bhi ho rahi hai ya ji matla raha hai?",
        "pain_location": "Dard bilkul kahan hai — upar, neeche, daain, ya baain taraf?",
        # RESPIRATORY pathway discriminators
        "chest_tightness": "Kya seenay mein jakran ya bhaari pan mehsoos ho raha hai?",
        "blood_in_cough": "Kya khansi mein khoon aata hai?",
        # GYNECOLOGICAL pathway discriminators
        "pregnancy_status": "Kya hamal ka koi imkaan hai?",
        "bleeding_pattern": "Khoon ka bahao kaisa hai — zyada, halka, ya thoda thoda?",
        "pain_severity_location": "Dard kahan hai — ek taraf ya dono taraf — aur kitna shadeed hai?",
        # UROLOGICAL pathway discriminators
        "blood_in_urine": "Kya peshab mein khoon aa raha hai?",
        "flank_pain": "Kya pehlu ya kamar mein, paslion ke neeche, dard hai?",
        # MUSCULOSKELETAL pathway discriminators
        "injury_history": "Kya yeh kisi chot ya girne ke baad shuru hua ya khud ba khud?",
        "swelling_present": "Kya us jagah sujan, lali, ya garmi hai?",
        "movement_limitation": "Kya aap us hisse ko normal tareeqe se hila sakte hain?",
        # MENTAL_HEALTH pathway discriminators
        "sleep_impact": "Aapki neend kaisi rahi hai — kam, zyada, ya sone mein mushkil?",
        "daily_function_impact": "Yeh feelings aapki roz marra zindagi ko kaise mutasir kar rahi hain?",
        "support_system": "Kya ghar wale ya dost hain jin par aap sahara le sakte hain?",
    },
}

_STUB_RECOMMENDATION_EN = (
    "Based on what you've shared, I'd suggest seeing a **{specialty_plain}**.\n\n"
    "Urgency: {urgency_text}\n\n"
    "Remember, this is guidance only — please consult the doctor for a proper evaluation. Take care!"
)

_STUB_RECOMMENDATION_UR = (
    "Aap ne jo bataya hai us ke mutabiq, main {specialty_plain} ke paas jaane ka mashwara doonga.\n\n"
    "Fori zaroorat: {urgency_text}\n\n"
    "Yaad rakhein, yeh sirf rahnumai hai — doctor se zaroor mil kar proper jaanch karayein. Apna khayal rakhein!"
)


# ── Helpers ───────────────────────────────────────────────────────────────


def _format_conversation_history(messages: list[Message]) -> str:
    """Format conversation messages for prompt context."""
    if not messages:
        return "(No previous messages)"
    lines = []
    for msg in messages:
        role_label = "PATIENT" if msg.role == "user" else "SYSTEM"
        lines.append(f"{role_label}: {msg.message_text}")
    return "\n".join(lines)


def _format_known_facts(facts: ExtractedFacts) -> str:
    """Format known facts for prompt context."""
    fact_dict = facts.model_dump(exclude_none=True, exclude_defaults=True)
    if not fact_dict:
        return "(No facts known yet)"
    lines = []
    for key, value in fact_dict.items():
        if isinstance(value, list) and value:
            lines.append(f"- {key}: {', '.join(str(v) for v in value)}")
        elif not isinstance(value, list):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "(No facts known yet)"


def _urgency_text(urgency: Urgency, language: Language) -> str:
    """Get human-readable urgency text."""
    if language == Language.UR:
        return {
            Urgency.ROUTINE: "Aap apni suvidha ke mutabiq appointment le sakte hain.",
            Urgency.URGENT: "24 ghanton ke andar doctor se milne ki koshish karein.",
            Urgency.EMERGENCY: "ABHI 1122 call karein!",
        }.get(urgency, "Appointment le lein.")
    return {
        Urgency.ROUTINE: "You can schedule an appointment at your convenience.",
        Urgency.URGENT: "Please try to see a doctor within 24 hours.",
        Urgency.EMERGENCY: "Call 1122 IMMEDIATELY!",
    }.get(urgency, "Schedule an appointment.")


# ── Public API ────────────────────────────────────────────────────────────


async def compose_follow_up(
    conversation_history: list[Message],
    facts: ExtractedFacts,
    missing_facts: list[str],
    language: Language,
    allow_sympathy: bool,
    discriminator_context: str | None = None,
    active_pathway: str | None = None,
) -> tuple[str, LLMCallMetadata | None]:
    """
    Generate a natural-language follow-up question for the patient.

    Uses the LLM to phrase the question naturally. When a clinical pathway
    discriminator is being asked, the discriminator_context is passed to the
    LLM so it can frame the question with appropriate urgency and empathy.
    Falls back to stub questions if the LLM is unavailable.

    Args:
        conversation_history:  All messages in the session.
        facts:                 Currently known facts.
        missing_facts:         List of missing fact names (priority-ordered).
        language:              Session language.
        discriminator_context: Clinical rationale for the current question
                               (from the matched pathway discriminator, or None
                               for baseline fact questions).
        active_pathway:        Pathway ID for logging (e.g. "CARDIAC").

    Returns:
        Tuple of (question text, LLM metadata or None).
    """
    first_missing = missing_facts[0] if missing_facts else "chief_complaint"
    lang_str = "Roman Urdu" if language == Language.UR else "English"

    if not settings.openai_api_key:
        # Fallback to stub questions
        lang_questions = _STUB_QUESTIONS.get(language, _STUB_QUESTIONS[Language.EN])
        question = lang_questions.get(
            first_missing,
            lang_questions.get("chief_complaint", "Tell me more about your symptoms."),
        )
        return question, None

    try:
        context_for_prompt = (
            discriminator_context
            or "(Standard intake question — no specific clinical pathway context.)"
        )

        sympathy_instruction = (
            "You may briefly express sympathy or acknowledge their suffering."
            if allow_sympathy
            else "DO NOT express sympathy, apologize, or say 'I am sorry' in this message. Just ask the question directly but warmly."
        )

        user_prompt = FOLLOW_UP_USER_TEMPLATE.format(
            language=lang_str,
            conversation_history=_format_conversation_history(conversation_history),
            known_facts=_format_known_facts(facts),
            missing_fact=first_missing,
            all_missing_facts=", ".join(missing_facts),
            discriminator_context=context_for_prompt,
            sympathy_instruction=sympathy_instruction,
        )

        text, metadata = await call_text(
            system_prompt=FOLLOW_UP_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            prompt_version=settings.response_composition_prompt_version,
            temperature=0.7,
        )

        # Sanitize: strip quotes, ensure it's not too long
        text = text.strip().strip('"').strip("'")
        if len(text) > 500:
            text = text[:500]

        logger.info(
            "Follow-up question composed in %dms (missing: %s, pathway: %s)",
            metadata.latency_ms,
            first_missing,
            active_pathway or "GENERAL",
        )
        return text, metadata

    except Exception as e:
        logger.error("Response composition failed, using stub: %s", e)
        lang_questions = _STUB_QUESTIONS.get(language, _STUB_QUESTIONS[Language.EN])
        question = lang_questions.get(first_missing, "Tell me more about your symptoms.")
        return question, None


async def compose_recommendation(
    conversation_history: list[Message],
    facts: ExtractedFacts,
    specialty: Specialty,
    urgency: Urgency,
    language: Language,
    allow_sympathy: bool,
) -> tuple[str, LLMCallMetadata | None]:
    """
    Generate the specialty recommendation message for the patient.

    Uses the LLM to generate a warm, clear recommendation. Falls back
    to a stub template if the LLM is unavailable.

    Args:
        conversation_history: All messages in the session.
        facts: All extracted facts.
        specialty: The recommended specialty.
        urgency: The urgency level.
        language: Session language.

    Returns:
        Tuple of (recommendation text, LLM metadata or None).
    """
    lang_key = "ur" if language == Language.UR else "en"
    lang_str = "Roman Urdu" if language == Language.UR else "English"
    specialty_names = SPECIALTY_PLAIN_NAMES.get(lang_key, SPECIALTY_PLAIN_NAMES["en"])
    specialty_plain = specialty_names.get(specialty.value, specialty.value)
    u_text = _urgency_text(urgency, language)

    if not settings.openai_api_key:
        # Fallback to stub template
        template = _STUB_RECOMMENDATION_UR if language == Language.UR else _STUB_RECOMMENDATION_EN
        return template.format(specialty_plain=specialty_plain, urgency_text=u_text), None

    try:
        sympathy_instruction = (
            "You may briefly express sympathy or acknowledge their suffering."
            if allow_sympathy
            else "DO NOT express sympathy, apologize, or say 'I am sorry' in this message. Just ask the question directly but warmly."
        )

        user_prompt = RECOMMENDATION_USER_TEMPLATE.format(
            language=lang_str,
            conversation_history=_format_conversation_history(conversation_history),
            known_facts=_format_known_facts(facts),
            specialty=specialty.value,
            specialty_plain=specialty_plain,
            urgency=urgency.value,
            sympathy_instruction=sympathy_instruction,
        )

        text, metadata = await call_text(
            system_prompt=RECOMMENDATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            prompt_version=settings.response_composition_prompt_version,
            temperature=0.7,
        )

        text = text.strip()
        if len(text) > 1000:
            text = text[:1000]

        logger.info(
            "Recommendation composed in %dms (specialty: %s, urgency: %s)",
            metadata.latency_ms,
            specialty.value,
            urgency.value,
        )
        return text, metadata

    except Exception as e:
        logger.error("Recommendation composition failed, using stub: %s", e)
        template = _STUB_RECOMMENDATION_UR if language == Language.UR else _STUB_RECOMMENDATION_EN
        return template.format(specialty_plain=specialty_plain, urgency_text=u_text), None
