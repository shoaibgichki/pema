"""
Policy engine — determines the next action based on session state and facts (FR-02.2, FR-04.4).

THIS IS THE DETERMINISTIC BRAIN OF THE SYSTEM.
All control flow decisions are made here in code, not by the LLM.

Clinical pathway integration:
  The engine now uses symptom-specific clinical pathways to determine the
  priority of follow-up questions. Instead of a flat required-facts list,
  questions are asked in this order:
    1. chief_complaint       (always first — needed to select a pathway)
    2. Pathway discriminators (ordered per the matched pathway)
    3. Remaining baseline facts (age, sex, duration, severity)
    4. Conditional facts     (is_pregnant, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import settings
from app.engine.clinical_pathways import (
    GENERAL_PATHWAY,
    ClinicalPathway,
    Discriminator,
    get_unanswered_discriminators,
    match_pathway,
)
from app.engine.safety_rules import SafetyRuleMatch
from app.schemas.enums import Specialty, Urgency
from app.schemas.fact import ExtractedFacts


# ── Decision Data Structures ─────────────────────────────────────────────


@dataclass
class PolicyDecision:
    """The output of the policy engine: what to do next."""

    action: str  # "ask" | "escalate" | "complete"
    missing_facts: list[str] = field(default_factory=list)
    specialty: Specialty | None = None
    urgency: Urgency | None = None
    confidence: float = 0.0
    escalation_reason: str | None = None
    # Clinical pathway context — passed downstream to the response composer
    # so the LLM can phrase discriminator questions with clinical awareness.
    active_pathway: str | None = None        # e.g. "CARDIAC"
    active_discriminator: str | None = None  # e.g. "shortness_of_breath"
    discriminator_context: str | None = None # clinical rationale for the LLM


# ── Fact Requirements ────────────────────────────────────────────────────

# Baseline facts collected for every patient, regardless of pathway.
# chief_complaint is checked first before pathway matching, then skipped
# in the baseline loop (it is always Priority 1, handled separately).
REQUIRED_FACTS = [
    "chief_complaint",  # Priority 1 — needed to select a clinical pathway
    "age",              # Priority 3a (after pathway discriminators)
    "sex",              # Priority 3b
    "duration",         # Priority 3c
    "severity",         # Priority 3d
]

# Conditionally required
CONDITIONAL_FACTS = {
    "is_pregnant": lambda facts: (
        facts.sex is not None
        and facts.sex.lower() == "female"
        and facts.age is not None
        and 12 <= facts.age <= 55
    ),
}


# ── Specialty Mapping Rules (FR-04.4 — deterministic, configurable) ──────

# Each rule: (Specialty, keywords_en, keywords_ur)
# Keywords are matched against chief_complaint, body_region, and associated_symptoms.
# Order matters — first match wins (most specific rules first).

SPECIALTY_RULES: list[tuple[Specialty, list[str], list[str]]] = [
    # Gastroenterology
    (
        Specialty.GASTROENTEROLOGIST,
        [
            "stomach", "digestion", "digestive", "nausea", "bloating", "abdomen",
            "abdominal", "gastric", "acid reflux", "heartburn", "indigestion",
            "vomiting", "diarrhea", "constipation", "bowel",
        ],
        [
            "pet dard", "pet mein dard", "maida", "maday", "hazma", "ulti",
            "dasst", "qabz", "pait", "tezab",
        ],
    ),
    # Dermatology
    (
        Specialty.DERMATOLOGIST,
        [
            "skin", "rash", "itching", "itch", "lesion", "acne", "eczema",
            "psoriasis", "hives", "boil", "fungal", "allergy skin",
            "dry skin", "wound",
        ],
        [
            "jild", "daane", "phunsiyan", "khujli", "charma", "kharish",
            "phulsi", "jild par",
        ],
    ),
    # ENT
    (
        Specialty.ENT,
        [
            "ear pain", "ear ache", "hearing", "nose", "nasal", "sinus",
            "sinusitis", "throat", "sore throat", "tonsil", "voice",
            "hoarse",
        ],
        [
            "kaan", "kaan dard", "naak", "naak band", "gala", "gale mein dard",
            "tonsil", "sunai",
        ],
    ),
    # Pulmonology
    (
        Specialty.PULMONOLOGIST,
        [
            "cough", "wheeze", "wheezing", "breathing", "lung", "respiratory",
            "asthma", "bronchitis", "pneumonia", "shortness of breath",
            "chest congestion",
        ],
        [
            "khansee", "khansi", "saans", "saans lene", "phephre", "phephron",
            "dam", "seene mein jakran",
        ],
    ),
    # Orthopedics
    (
        Specialty.ORTHOPEDIST,
        [
            "joint", "bone", "muscle", "knee", "back pain", "spine", "fracture",
            "sprain", "shoulder", "hip", "arthritis", "swelling joint",
            "ligament", "neck pain",
        ],
        [
            "jor dard", "jor", "haddi", "gathiya", "gathiyon", "kamar dard",
            "ghutna", "kandha", "reedh", "haddiyon",
        ],
    ),
    # Neurology
    (
        Specialty.NEUROLOGIST,
        [
            "headache", "migraine", "neuro", "vision", "numbness", "dizziness",
            "dizzy", "vertigo", "tingling", "tremor", "memory",
            "blurred vision", "nerve",
        ],
        [
            "sar dard", "sar mein dard", "chakkar", "nazar", "aankhon",
            "sunnpan", "junaun", "yaaddasht",
        ],
    ),
    # Urology
    (
        Specialty.UROLOGIST,
        [
            "urinary", "urine", "urination", "kidney", "bladder", "blood in urine",
            "painful urination", "frequent urination", "kidney stone",
            "prostate",
        ],
        [
            "peshab", "peshab mein", "gurda", "gurde", "masana",
            "peshab mein khoon", "peshab mein jalan",
        ],
    ),
    # Psychiatry
    (
        Specialty.PSYCHIATRIST,
        [
            "anxiety", "depression", "depressed", "insomnia", "mental",
            "stress", "panic", "mood", "sadness", "sleep problem",
            "sleep disorder", "ptsd", "ocd",
        ],
        [
            "ghabrahat", "neend nahi", "neend nahi aati", "pareshani", "udasi",
            "tension", "dimagh", "zehan",
        ],
    ),
    # Gynecology
    (
        Specialty.GYNECOLOGIST,
        [
            "menstrual", "period", "periods", "pelvic", "vaginal", "ovary",
            "uterus", "menopause", "irregular period", "cramp",
            "gynecological", "pcos", "pregnancy",
        ],
        [
            "haiz", "mahwari", "pelvic dard", "bacha dani", "mahwari band",
            "hamal", "aurat ki bimari",
        ],
    ),
]


def _get_symptom_text(facts: ExtractedFacts) -> str:
    """
    Combine all symptom-related text from facts into a single searchable string.

    Includes chief_complaint, body_region, associated_symptoms, and additional_context.
    """
    parts: list[str] = []
    if facts.chief_complaint:
        parts.append(facts.chief_complaint)
    if facts.body_region:
        parts.append(facts.body_region)
    if facts.associated_symptoms:
        parts.extend(facts.associated_symptoms)
    if facts.additional_context:
        parts.append(facts.additional_context)
    return " ".join(parts).lower()


def _keyword_match_count(text: str, keywords: list[str]) -> int:
    """Count how many keywords from the list are found in the text."""
    count = 0
    for kw in keywords:
        if kw.lower() in text:
            count += 1
    return count


def _parse_duration_days(duration: str | None) -> int | None:
    """
    Attempt to parse a duration string into approximate number of days.

    Returns None if the duration cannot be parsed.
    """
    if not duration:
        return None

    text = duration.lower().strip()

    # Match patterns like "3 days", "2 weeks", "1 month", "1 hafta"
    match = re.search(r"(\d+)\s*(day|din|week|hafta|month|mahin|mahina|year|saal)", text)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit in ("day", "din"):
        return value
    elif unit in ("week", "hafta"):
        return value * 7
    elif unit in ("month", "mahin", "mahina"):
        return value * 30
    elif unit in ("year", "saal"):
        return value * 365
    return None


def compute_recommendation(
    facts: ExtractedFacts,
    pathway: ClinicalPathway | None = None,
) -> tuple[Specialty, Urgency, float]:
    """
    Map collected facts to a specialty, urgency level, and confidence score.

    This is the deterministic specialty routing engine (FR-04.4).
    All decisions are rules-based — no LLM involvement.

    Args:
        facts:   The fully (or partially) extracted clinical facts.
        pathway: The active clinical pathway (used as a specialty/urgency hint).
                 When the keyword match agrees with the pathway hint, confidence
                 is boosted. When the pathway defines an urgency_bias, it is
                 applied as a floor (never downgraded below it).

    Returns:
        Tuple of (Specialty, Urgency, confidence_score).
    """
    symptom_text = _get_symptom_text(facts)
    best_specialty = Specialty.GENERAL_PRACTITIONER
    best_score = 0

    # 1. Pediatric routing: children under 12 go to pediatrician first
    if facts.age is not None and facts.age < 12:
        best_specialty = Specialty.PEDIATRICIAN
        best_score = 3  # decent match for being a child
        # Still run keyword matching — a strong specialty match overrides pediatrician

    # 2. Keyword-based specialty matching
    for specialty, keywords_en, keywords_ur in SPECIALTY_RULES:
        en_hits = _keyword_match_count(symptom_text, keywords_en)
        ur_hits = _keyword_match_count(symptom_text, keywords_ur)
        total_hits = en_hits + ur_hits

        if total_hits > best_score:
            best_score = total_hits
            best_specialty = specialty

    # 3. Pathway specialty hint: if keyword match agrees with pathway hint,
    #    boost score to reflect corroborating evidence.
    if (
        pathway is not None
        and pathway.pathway_id != "GENERAL"
        and best_specialty == pathway.specialty_hint
    ):
        best_score += 1  # corroboration boost

    # 4. Urgency determination
    urgency = _compute_urgency(facts, best_specialty, symptom_text)

    # 5. Apply pathway urgency bias (floor — never downgrade below it)
    if pathway is not None and pathway.urgency_bias is not None:
        urgency_order = [Urgency.ROUTINE, Urgency.URGENT, Urgency.EMERGENCY]
        if urgency_order.index(urgency) < urgency_order.index(pathway.urgency_bias):
            urgency = pathway.urgency_bias

    # 6. Confidence scoring
    confidence = _compute_confidence(best_score, facts)

    # 7. Low confidence → default to GP
    if confidence < 0.7:
        best_specialty = Specialty.GENERAL_PRACTITIONER

    return best_specialty, urgency, confidence


def _compute_urgency(
    facts: ExtractedFacts,
    specialty: Specialty,
    symptom_text: str,
) -> Urgency:
    """
    Compute urgency level based on severity, duration, and clinical signals.

    Urgency modifiers (applied after initial mapping):
    - Severity = "severe" → bump urgency one level (routine → urgent)
    - Duration > 2 weeks → consider urgent if currently routine
    - Blood mentioned in symptoms → at minimum urgent
    - Child under 5 with fever → urgent minimum
    """
    urgency = Urgency.ROUTINE

    # Severity modifier
    if facts.severity and facts.severity.lower() == "severe":
        urgency = Urgency.URGENT

    # Duration modifier: > 14 days → urgent
    duration_days = _parse_duration_days(facts.duration)
    if duration_days is not None and duration_days > 14:
        if urgency == Urgency.ROUTINE:
            urgency = Urgency.URGENT

    # Blood in symptoms → at minimum urgent
    blood_keywords = ["blood", "bleeding", "khoon"]
    for kw in blood_keywords:
        if kw in symptom_text:
            if urgency == Urgency.ROUTINE:
                urgency = Urgency.URGENT
            break

    # Child under 5 with fever → urgent minimum
    fever_keywords = ["fever", "bukhar", "tez bukhar"]
    if facts.age is not None and facts.age < 5:
        for kw in fever_keywords:
            if kw in symptom_text:
                if urgency == Urgency.ROUTINE:
                    urgency = Urgency.URGENT
                break

    return urgency


def _compute_confidence(match_score: int, facts: ExtractedFacts) -> float:
    """
    Compute a confidence score (0.0–1.0) for the specialty mapping.

    - 3+ keyword matches → high confidence (0.9)
    - 2 matches → medium-high (0.8)
    - 1 match → medium (0.7)
    - 0 matches → low (0.5)
    - Missing critical facts reduces confidence by 0.1 per missing fact
    """
    if match_score >= 3:
        confidence = 0.95
    elif match_score == 2:
        confidence = 0.85
    elif match_score == 1:
        confidence = 0.75
    else:
        confidence = 0.5

    # Penalize for missing important facts
    if not facts.chief_complaint:
        confidence -= 0.1
    if facts.age is None:
        confidence -= 0.05
    if facts.severity is None:
        confidence -= 0.05

    return max(0.1, min(1.0, confidence))


# ── Public API ────────────────────────────────────────────────────────────


def decide_next_action(
    facts: ExtractedFacts,
    rule_matches: list[SafetyRuleMatch],
    turn_count: int,
    raw_history: str = "",
) -> PolicyDecision:
    """
    Determine the next action for the triage engine.

    Priority order for follow-up questions:
      1. Emergency escalation (safety rules — overrides everything)
      2. chief_complaint (needed before pathway can be selected)
      3. Pathway-specific discriminators (ordered per clinical pathway)
      4. Baseline facts (age, sex, duration, severity)
      5. Conditional facts (is_pregnant)

    Args:
        facts: Currently extracted clinical facts.
        rule_matches: Safety rules triggered on this turn.
        turn_count: Number of user turns so far.
        raw_history: Concatenated raw user text from all turns.

    Returns:
        PolicyDecision indicating what the engine should do next.
    """
    # 1. Emergency rules override everything (FR-03.3)
    from app.engine.safety_rules import has_emergency

    if has_emergency(rule_matches):
        return PolicyDecision(
            action="escalate",
            urgency=Urgency.EMERGENCY,
            specialty=Specialty.EMERGENCY_DEPARTMENT,
            confidence=1.0,
            escalation_reason=rule_matches[0].rule_name,
        )

    # 2. Compute missing facts using the pathway-aware priority system
    missing, active_pathway, unanswered_discriminators = _get_missing_facts(facts, raw_history)

    # 3. Turn limit check (FR-02.3)
    if turn_count >= settings.max_follow_up_turns and missing:
        # Can't ask more questions — compute best recommendation with available data
        specialty, urgency, confidence = compute_recommendation(facts, active_pathway)
        # Cap confidence for incomplete data
        confidence = min(confidence, 0.5)
        return PolicyDecision(
            action="complete",
            missing_facts=missing,
            specialty=specialty,
            urgency=urgency,
            confidence=confidence,
            active_pathway=active_pathway.pathway_id,
        )

    # 4. If we have all required facts, compute recommendation
    if not missing:
        specialty, urgency, confidence = compute_recommendation(facts, active_pathway)
        return PolicyDecision(
            action="complete",
            missing_facts=[],
            specialty=specialty,
            urgency=urgency,
            confidence=confidence,
            active_pathway=active_pathway.pathway_id,
        )

    # 5. Ask for the next missing fact
    #    If the top missing fact is a pathway discriminator, attach clinical context.
    next_missing = missing[0]
    discriminator_context: str | None = None
    active_discriminator: str | None = None

    if unanswered_discriminators:
        # The first unanswered discriminator matches the first missing fact
        top_disc = unanswered_discriminators[0]
        if top_disc.fact_key == next_missing:
            active_discriminator = top_disc.fact_key
            discriminator_context = top_disc.question_context

    return PolicyDecision(
        action="ask",
        missing_facts=missing,
        active_pathway=active_pathway.pathway_id,
        active_discriminator=active_discriminator,
        discriminator_context=discriminator_context,
    )


def _get_missing_facts(
    facts: ExtractedFacts,
    raw_history: str = "",
) -> tuple[list[str], ClinicalPathway, list[Discriminator]]:
    """
    Determine which facts are still missing, using a 4-layer priority system.

    Priority:
      1. chief_complaint — always first; needed to select a pathway
      2. Pathway discriminators — ordered per the matched clinical pathway
      3. Remaining baseline facts — age, sex, duration, severity
      4. Conditional facts — is_pregnant (when applicable)

    Returns:
        Tuple of:
          - Ordered list of missing fact keys
          - The active ClinicalPathway (GENERAL_PATHWAY if unmatched)
          - List of unanswered Discriminator objects (empty for GENERAL pathway)
    """
    # Priority 1: chief_complaint is always the very first question.
    # Without it we cannot select a pathway.
    if not facts.chief_complaint or not facts.chief_complaint.strip():
        return ["chief_complaint"], GENERAL_PATHWAY, []

    # Select the clinical pathway based on the extracted chief complaint and raw history
    active_pathway = match_pathway(facts, raw_history)

    missing: list[str] = []

    # Priority 2: Pathway-specific discriminators
    unanswered = get_unanswered_discriminators(active_pathway, facts)
    for disc in unanswered:
        missing.append(disc.fact_key)

    # Priority 3: Remaining baseline facts
    # Skip chief_complaint — already confirmed present above.
    for fact_name in REQUIRED_FACTS:
        if fact_name == "chief_complaint":
            continue
        value = getattr(facts, fact_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(fact_name)

    # Priority 4: Conditional facts
    for fact_name, condition_fn in CONDITIONAL_FACTS.items():
        if condition_fn(facts):
            value = getattr(facts, fact_name, None)
            if value is None:
                # Avoid duplicating pregnancy: GYNECOLOGICAL pathway already adds
                # "pregnancy_status" discriminator which covers the same question.
                if fact_name == "is_pregnant" and "pregnancy_status" in missing:
                    continue
                if fact_name not in missing:
                    missing.append(fact_name)

    return missing, active_pathway, unanswered
