"""
Clinical Pathways — symptom-specific triage question sequences (FR-02.2).

This module implements the 'protocol-driven' layer of the policy engine.
Each ClinicalPathway maps a chief complaint to an ordered list of
discriminator questions that must be answered before baseline facts are
collected — mirroring standard hospital triage protocols.

Design principles:
- Pure data + matching logic. Zero LLM involvement.
- Pathway selection is based on the LLM-extracted chief_complaint,
  which is already normalized / translated by the fact extractor.
- Discriminator answers are stored in facts.associated_symptoms —
  no schema change required.
- Unmatched complaints fall through to GENERAL_PATHWAY which uses
  the existing flat-list logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.enums import Specialty, Urgency
from app.schemas.fact import ExtractedFacts


# ── Data Structures ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Discriminator:
    """
    A single clinical question a pathway needs answered.

    Attributes:
        fact_key:           Unique identifier (e.g. "shortness_of_breath").
                            Used to check whether this has already been answered.
        question_context:   Plain-English clinical rationale passed to the LLM
                            so it can phrase the question naturally and empathetically.
        answer_signals:     Keywords that, if present in associated_symptoms or
                            additional_context, indicate this discriminator is answered.
    """

    fact_key: str
    question_context: str
    answer_signals: tuple[str, ...]  # immutable for hashing


@dataclass(frozen=True)
class ClinicalPathway:
    """
    A complaint-specific triage pathway.

    Attributes:
        pathway_id:      Unique identifier (e.g. "CARDIAC").
        display_name:    Human-readable label for logs and audit trail.
        trigger_keywords: Matched against extracted chief_complaint (case-insensitive).
                          Also checked against body_region and associated_symptoms
                          for secondary signal.
        discriminators:  Ordered list — first unanswered = next question asked.
        specialty_hint:  Default specialty if pathway completes cleanly.
        urgency_bias:    Minimum urgency floor for this pathway (or None).
    """

    pathway_id: str
    display_name: str
    trigger_keywords: tuple[str, ...]
    discriminators: tuple[Discriminator, ...]
    specialty_hint: Specialty
    urgency_bias: Urgency | None = None


# ── Pathway Registry ─────────────────────────────────────────────────────────
#
# Order matters: more specific pathways should come before general ones.
# First match wins.

CARDIAC_PATHWAY = ClinicalPathway(
    pathway_id="CARDIAC",
    display_name="Chest Pain Pathway",
    trigger_keywords=(
        # Full-phrase matches (Pass 1 exact, or Pass 2 token-set for word-order variants)
        # e.g. "pain in my chest" matches via Pass 2 (tokens: chest + pain both present)
        "chest pain", "chest ache", "heart pain", "chest pressure", "chest tightness",
        "heart attack", "seenay mein dard", "seene mein dard", "dil mein dard",
        "seena dard", "dil ka dard",
        # Additional LLM-phrasing variants
        "chest discomfort", "chest hurt", "chest hurts", "cardiac pain",
    ),
    discriminators=(
        Discriminator(
            fact_key="shortness_of_breath",
            question_context=(
                "Ask if the patient is also experiencing shortness of breath or difficulty "
                "breathing. Shortness of breath combined with chest pain may indicate a "
                "cardiac emergency requiring immediate escalation."
            ),
            answer_signals=(
                "shortness of breath", "difficulty breathing", "can't breathe",
                "hard to breathe", "breathing difficulty", "breathless",
                "saans nahi", "saans lene mein mushkil", "saans ki takleef",
            ),
        ),
        Discriminator(
            fact_key="radiating_pain",
            question_context=(
                "Ask if the pain spreads or radiates to the arm (especially left arm), "
                "jaw, neck, or back. Radiating pain is a key indicator of a possible "
                "myocardial infarction (heart attack)."
            ),
            answer_signals=(
                "radiating", "spreads", "arm", "left arm", "jaw", "neck", "back",
                "baazu", "baazu mein", "jabda", "gardun", "peeth",
            ),
        ),
        Discriminator(
            fact_key="onset_type",
            question_context=(
                "Ask whether the chest pain came on suddenly or built up gradually. "
                "Sudden onset is more clinically concerning for acute cardiac events."
            ),
            answer_signals=(
                "sudden", "suddenly", "gradually", "slowly", "came on quickly",
                "achanak", "dheere dheere", "ek dam",
            ),
        ),
    ),
    specialty_hint=Specialty.PULMONOLOGIST,  # will be overridden by safety rules for true cardiac events
    urgency_bias=Urgency.URGENT,
)

NEUROLOGICAL_PATHWAY = ClinicalPathway(
    pathway_id="NEUROLOGICAL",
    display_name="Neurological Symptoms Pathway",
    trigger_keywords=(
        "headache", "migraine", "dizziness", "dizzy", "vertigo", "numbness",
        "tingling", "weakness", "confusion", "memory", "blurred vision",
        "sar dard", "sar mein dard", "chakkar", "sunnpan", "kamzori",
        "nazar dhundli", "yaaddasht",
        # Pass 2 will catch "pain in my head" via tokens {head, pain}
        # but also add direct variants for common LLM normalizations:
        "head pain", "brain",
    ),
    discriminators=(
        Discriminator(
            fact_key="vision_changes",
            question_context=(
                "Ask if the patient has noticed any changes in their vision — such as "
                "blurred vision, double vision, or sudden vision loss. Vision changes "
                "alongside a headache or dizziness could indicate elevated intracranial "
                "pressure or a stroke."
            ),
            answer_signals=(
                "vision", "blurred", "double vision", "vision loss", "can't see",
                "blind", "nazar", "aankhon mein", "dhundla", "nazar kharab",
            ),
        ),
        Discriminator(
            fact_key="numbness_weakness",
            question_context=(
                "Ask if the patient has any one-sided numbness, weakness, or difficulty "
                "moving an arm or leg. Unilateral (one-sided) weakness or numbness is a "
                "key stroke discriminator."
            ),
            answer_signals=(
                "numbness", "weakness", "one side", "arm", "leg", "face drooping",
                "can't move", "sunnpan", "kamzori", "ek taraf", "baazu", "tang",
            ),
        ),
        Discriminator(
            fact_key="headache_onset",
            question_context=(
                "Ask how the headache started — was it a sudden, extremely severe "
                "'thunderclap' headache, or did it come on gradually? A sudden severe "
                "headache (the worst of their life) is a red flag for subarachnoid "
                "hemorrhage."
            ),
            answer_signals=(
                "sudden", "worst", "thunderclap", "immediately", "severe onset",
                "achanak", "ek dam", "bahut shadeed",
                "gradual", "gradually", "slowly", "developed gradually", "dheere dheere", "over time",
            ),
        ),
    ),
    specialty_hint=Specialty.NEUROLOGIST,
    urgency_bias=None,
)

ABDOMINAL_PATHWAY = ClinicalPathway(
    pathway_id="ABDOMINAL",
    display_name="Abdominal Pain Pathway",
    trigger_keywords=(
        "stomach", "stomach pain", "abdominal", "abdominal pain", "abdomen",
        "belly", "nausea", "vomiting", "pet dard", "pet mein dard", "pait",
        "pait dard", "maida", "ulti", "hazma",
    ),
    discriminators=(
        Discriminator(
            fact_key="fever_present",
            question_context=(
                "Ask if the patient also has a fever. Abdominal pain combined with fever "
                "may indicate appendicitis, peritonitis, or a serious abdominal infection "
                "requiring urgent evaluation."
            ),
            answer_signals=(
                "fever", "temperature", "hot", "chills", "bukhar", "tez bukhar",
                "garmi", "tapish",
            ),
        ),
        Discriminator(
            fact_key="vomiting_present",
            question_context=(
                "Ask if the patient has been vomiting and, if so, how many times. The "
                "pattern of vomiting helps differentiate simple gastritis from more "
                "serious surgical causes like appendicitis or bowel obstruction."
            ),
            answer_signals=(
                "vomiting", "vomited", "throwing up", "nausea", "ulti", "qay",
                "ultiyan", "ji matla raha",
            ),
        ),
        Discriminator(
            fact_key="pain_location",
            question_context=(
                "Ask the patient to describe exactly where in the abdomen the pain is "
                "located — upper, lower, left, right, or around the navel. Right lower "
                "quadrant pain specifically raises concern for appendicitis."
            ),
            answer_signals=(
                "right side", "lower right", "upper", "lower", "around navel",
                "belly button", "seedha", "ulta", "neeche", "upar", "daain",
                "baain", "naaf ke paas",
            ),
        ),
    ),
    specialty_hint=Specialty.GASTROENTEROLOGIST,
    urgency_bias=None,
)

RESPIRATORY_PATHWAY = ClinicalPathway(
    pathway_id="RESPIRATORY",
    display_name="Respiratory Symptoms Pathway",
    trigger_keywords=(
        "cough", "breathing", "breathlessness", "wheeze", "wheezing", "lung",
        "respiratory", "shortness of breath", "chest congestion",
        "khansi", "khansee", "saans", "saans ki takleef", "dam", "phephre",
        "seene mein jakran",
    ),
    discriminators=(
        Discriminator(
            fact_key="fever_present",
            question_context=(
                "Ask if the patient also has a fever. A cough or breathing difficulty "
                "combined with fever could indicate pneumonia, which may require urgent "
                "treatment."
            ),
            answer_signals=(
                "fever", "temperature", "hot", "chills", "bukhar", "tez bukhar",
                "garmi",
            ),
        ),
        Discriminator(
            fact_key="chest_tightness",
            question_context=(
                "Ask if the patient feels chest tightness or a sensation of pressure "
                "in the chest when breathing. This helps differentiate asthma or "
                "bronchospasm from other respiratory causes."
            ),
            answer_signals=(
                "tight", "tightness", "pressure", "constriction", "heavy chest",
                "jakran", "bhaari", "seena bhaari",
            ),
        ),
        Discriminator(
            fact_key="blood_in_cough",
            question_context=(
                "Ask very gently if the patient has noticed any blood when they cough. "
                "Hemoptysis (coughing blood) requires urgent evaluation as it can indicate "
                "serious lung conditions."
            ),
            answer_signals=(
                "blood", "bloody", "red", "pink mucus", "khansi mein khoon",
                "khoon aata hai",
            ),
        ),
    ),
    specialty_hint=Specialty.PULMONOLOGIST,
    urgency_bias=None,
)

GYNECOLOGICAL_PATHWAY = ClinicalPathway(
    pathway_id="GYNECOLOGICAL",
    display_name="Gynecological Symptoms Pathway",
    trigger_keywords=(
        "period", "periods", "menstrual", "menstruation", "pelvic", "pelvic pain",
        "vaginal", "ovary", "uterus", "irregular period", "cramp", "cramps",
        "haiz", "mahwari", "mahwari band", "hamal", "pelvic dard", "bacha dani",
    ),
    discriminators=(
        Discriminator(
            fact_key="pregnancy_status",
            question_context=(
                "Ask gently whether there is any possibility the patient could be "
                "pregnant. Pregnancy significantly changes the clinical differential "
                "and urgency — for example, ectopic pregnancy is life-threatening."
            ),
            answer_signals=(
                "pregnant", "pregnancy", "expecting", "hamal", "hamal hai",
                "hamal se hoon",
            ),
        ),
        Discriminator(
            fact_key="bleeding_pattern",
            question_context=(
                "Ask the patient to describe the bleeding — is it heavier than usual, "
                "lighter, or spotting? The pattern of abnormal uterine bleeding helps "
                "differentiate hormonal causes from structural ones."
            ),
            answer_signals=(
                "heavy", "light", "spotting", "clots", "irregular", "normal",
                "zyada khoon", "halka", "darmiyani",
            ),
        ),
        Discriminator(
            fact_key="pain_severity_location",
            question_context=(
                "Ask where the pelvic pain is — is it on one side or both sides — and "
                "how severe it is on a scale of mild to severe. Severe one-sided pelvic "
                "pain could indicate ovarian torsion or ectopic pregnancy."
            ),
            answer_signals=(
                "one side", "both sides", "sharp", "cramping", "left", "right",
                "ek taraf", "daain", "baain", "shadeed dard",
            ),
        ),
    ),
    specialty_hint=Specialty.GYNECOLOGIST,
    urgency_bias=None,
)

UROLOGICAL_PATHWAY = ClinicalPathway(
    pathway_id="UROLOGICAL",
    display_name="Urological Symptoms Pathway",
    trigger_keywords=(
        "urinary", "urination", "urine", "pee", "bladder", "kidney", "kidney stone",
        "painful urination", "frequent urination", "burning urination",
        "peshab", "peshab mein", "gurda", "gurde", "masana", "peshab mein jalan",
        "peshab zyada aata",
    ),
    discriminators=(
        Discriminator(
            fact_key="blood_in_urine",
            question_context=(
                "Ask whether the patient has noticed any blood in their urine (it may "
                "appear pink, red, or cola-coloured). Blood in urine (haematuria) "
                "requires urgent evaluation to rule out infection, stones, or more "
                "serious causes."
            ),
            answer_signals=(
                "blood", "bloody", "pink", "red", "dark", "cola", "khoon",
                "peshab mein khoon", "rang badla",
            ),
        ),
        Discriminator(
            fact_key="fever_present",
            question_context=(
                "Ask whether the patient also has a fever or chills. Urinary symptoms "
                "with fever suggest a kidney infection (pyelonephritis), which is more "
                "serious than a simple bladder infection and may need urgent treatment."
            ),
            answer_signals=(
                "fever", "chills", "hot", "temperature", "bukhar", "thand",
                "kaanpna",
            ),
        ),
        Discriminator(
            fact_key="flank_pain",
            question_context=(
                "Ask if the patient has any pain in their side or back — specifically "
                "in the flank area (the region between the ribs and hip). Flank pain "
                "combined with urinary symptoms strongly suggests kidney stones."
            ),
            answer_signals=(
                "flank", "side", "back", "kidney area", "below ribs",
                "kamar", "kamar dard", "pehlu", "pehlu mein dard",
            ),
        ),
    ),
    specialty_hint=Specialty.UROLOGIST,
    urgency_bias=None,
)

MUSCULOSKELETAL_PATHWAY = ClinicalPathway(
    pathway_id="MUSCULOSKELETAL",
    display_name="Musculoskeletal Pain Pathway",
    trigger_keywords=(
        "joint pain", "joint", "bone", "muscle", "knee", "back pain", "spine",
        "fracture", "sprain", "shoulder", "hip", "neck pain", "arthritis",
        "jor dard", "jor", "haddi", "gathiya", "kamar dard", "ghutna",
        "kandha", "reedh", "muscle pain",
    ),
    discriminators=(
        Discriminator(
            fact_key="injury_history",
            question_context=(
                "Ask whether the pain started after a specific injury, fall, or accident, "
                "or whether it came on by itself without any trauma. Recent injury changes "
                "the differential entirely — possible fracture, sprain, or ligament tear."
            ),
            answer_signals=(
                "injury", "fall", "accident", "twisted", "hit", "trauma",
                "chot", "gira", "girna", "mochi", "takkar",
            ),
        ),
        Discriminator(
            fact_key="swelling_present",
            question_context=(
                "Ask if there is any swelling, redness, or warmth in the affected joint "
                "or area. Swelling with redness may indicate inflammatory arthritis, "
                "gout, or joint infection (septic arthritis)."
            ),
            answer_signals=(
                "swelling", "swollen", "red", "warm", "puffy",
                "sujan", "lali", "garmi", "phula hua",
            ),
        ),
        Discriminator(
            fact_key="movement_limitation",
            question_context=(
                "Ask whether the patient is able to move the affected area normally, "
                "or if movement is restricted or painful. Inability to bear weight on a "
                "limb or move a joint suggests a more serious injury requiring imaging."
            ),
            answer_signals=(
                "can't move", "limited movement", "stiff", "restricted",
                "can't walk", "bear weight", "hilana mushkil", "chal nahi sakta",
                "akad",
            ),
        ),
    ),
    specialty_hint=Specialty.ORTHOPEDIST,
    urgency_bias=None,
)

MENTAL_HEALTH_PATHWAY = ClinicalPathway(
    pathway_id="MENTAL_HEALTH",
    display_name="Mental Health Pathway",
    trigger_keywords=(
        "anxiety", "depression", "depressed", "stress", "panic", "panic attack",
        "mood", "sad", "sadness", "sleep problem", "insomnia", "mental health",
        "ptsd", "ocd", "feeling low", "hopeless",
        "ghabrahat", "neend nahi", "udasi", "pareshani", "tension", "dimagh",
        "zehan", "neend nahi aati",
    ),
    discriminators=(
        Discriminator(
            fact_key="sleep_impact",
            question_context=(
                "Ask how their sleep has been affected — are they sleeping too much, "
                "too little, or having trouble falling or staying asleep? Sleep "
                "disturbance is a key severity indicator for depression and anxiety."
            ),
            answer_signals=(
                "sleep", "insomnia", "sleeping too much", "can't sleep", "nightmares",
                "neend", "neend nahi", "neend zyada",
            ),
        ),
        Discriminator(
            fact_key="daily_function_impact",
            question_context=(
                "Ask gently how these feelings are affecting their daily life — work, "
                "relationships, or daily activities. Functional impairment is a key "
                "indicator of severity requiring more urgent professional support."
            ),
            answer_signals=(
                "work", "relationships", "daily", "function", "can't do", "affecting",
                "kaam", "ghar", "roz marra", "kuch nahi kar sakta",
            ),
        ),
        Discriminator(
            fact_key="support_system",
            question_context=(
                "Ask whether they have friends, family, or any support system they can "
                "lean on. Isolation is a risk factor that affects urgency and routing."
            ),
            answer_signals=(
                "family", "friends", "support", "alone", "isolated", "no one",
                "ghar wale", "dost", "akela", "koi nahi",
            ),
        ),
    ),
    specialty_hint=Specialty.PSYCHIATRIST,
    urgency_bias=None,
)

# The general fallback pathway — no discriminators.
# Uses the existing flat REQUIRED_FACTS logic in the policy engine.
GENERAL_PATHWAY = ClinicalPathway(
    pathway_id="GENERAL",
    display_name="General Symptoms Pathway",
    trigger_keywords=(),  # never directly matched — always the fallback
    discriminators=(),    # no discriminators — go straight to baseline facts
    specialty_hint=Specialty.GENERAL_PRACTITIONER,
    urgency_bias=None,
)

# Registry — ordered most-specific first.
# GENERAL_PATHWAY is the implicit fallback and not in this list.
ALL_PATHWAYS: tuple[ClinicalPathway, ...] = (
    CARDIAC_PATHWAY,
    NEUROLOGICAL_PATHWAY,
    ABDOMINAL_PATHWAY,
    RESPIRATORY_PATHWAY,
    GYNECOLOGICAL_PATHWAY,
    UROLOGICAL_PATHWAY,
    MUSCULOSKELETAL_PATHWAY,
    MENTAL_HEALTH_PATHWAY,
)

# ── Body Region Anchor Map ───────────────────────────────────────────────────
# Maps a single body_region word to a pathway.
# Used as a secondary match when the full trigger_keywords miss (e.g., when the
# LLM produces "pain in my chest" instead of "chest pain").
_BODY_REGION_PATHWAY_MAP: dict[str, ClinicalPathway] = {
    "chest":   CARDIAC_PATHWAY,
    "heart":   CARDIAC_PATHWAY,
    "head":    NEUROLOGICAL_PATHWAY,
    "abdomen": ABDOMINAL_PATHWAY,
    "stomach": ABDOMINAL_PATHWAY,
    "pelvic":  GYNECOLOGICAL_PATHWAY,
    "urinary": UROLOGICAL_PATHWAY,
    "kidney":  UROLOGICAL_PATHWAY,
    "back":    MUSCULOSKELETAL_PATHWAY,
    "joint":   MUSCULOSKELETAL_PATHWAY,
    "joints":  MUSCULOSKELETAL_PATHWAY,
    "knee":    MUSCULOSKELETAL_PATHWAY,
    "shoulder": MUSCULOSKELETAL_PATHWAY,
    "skin":    MENTAL_HEALTH_PATHWAY,  # skin rash → no pathway; keeps GENERAL
}

# Correct skin to general (it doesn't have a pathway)
del _BODY_REGION_PATHWAY_MAP["skin"]


# ── Pathway Matching ─────────────────────────────────────────────────────────


def _keyword_tokens_match(keyword: str, search_text: str) -> bool:
    """
    Return True if all space-separated tokens in 'keyword' appear anywhere
    in 'search_text' as whole words or substrings.

    This catches word-order variants:
      keyword="chest pain"  matches  search_text="pain in my chest"
    """
    tokens = keyword.lower().split()
    return all(tok in search_text for tok in tokens)


def match_pathway(facts: ExtractedFacts, raw_history: str = "") -> ClinicalPathway:
    """
    Match extracted facts to the most appropriate clinical pathway.

    Three-pass matching (highest → lowest confidence):
      Pass 1 — Exact phrase: keyword appears as a contiguous substring.
               e.g. chief_complaint="chest pain" matches CARDIAC.
      Pass 2 — Token-set: all keyword tokens appear (any order/position).
               e.g. chief_complaint="pain in my chest" → tokens {"chest","pain"}
               both found in the text → matches CARDIAC.
      Pass 3 — Body-region anchor: body_region field contains a known anchor
               word from _BODY_REGION_PATHWAY_MAP.
               e.g. body_region="chest" → CARDIAC.

    Uses `raw_history` as a fallback search corpus in Pass 1 and Pass 2 to
    protect against weak LLMs that overly summarize the chief complaint.

    Args:
        facts: Currently extracted clinical facts.
        raw_history: Concatenated raw user text from all turns.

    Returns:
        The matched ClinicalPathway, or GENERAL_PATHWAY if no match found.
    """
    # Build primary search text (all complaint-related fields, lowercase)
    search_parts: list[str] = []
    if facts.chief_complaint:
        search_parts.append(facts.chief_complaint)
    if facts.associated_symptoms:
        search_parts.extend(facts.associated_symptoms)
    if facts.additional_context:
        search_parts.append(facts.additional_context)

    primary_text = " ".join(search_parts).lower()

    # Include body_region in a wider text (for pass 1 & 2 only—
    # body_region gets its own dedicated pass 3 below)
    body_region_text = facts.body_region.lower() if facts.body_region else ""
    full_text = (primary_text + " " + body_region_text + " " + raw_history.lower()).strip()

    if not full_text:
        return GENERAL_PATHWAY

    # ── Strong Matches: Pass 1 & Pass 2 per Pathway ───────────────────────────
    # We check each pathway in priority order. For each pathway, we check Pass 1
    # (Exact phrase) and Pass 2 (Token-set). This prevents a lower-priority
    # pathway's exact match from overriding a higher-priority pathway's token match.
    for pathway in ALL_PATHWAYS:
        # Pass 1: Exact phrase match
        for keyword in pathway.trigger_keywords:
            if keyword.lower() in full_text:
                return pathway
                
        # Pass 2: Token-set match (order-agnostic)
        for keyword in pathway.trigger_keywords:
            if " " in keyword and _keyword_tokens_match(keyword, full_text):
                return pathway

    # ── Pass 3: Body-region anchor ────────────────────────────────────────────
    if body_region_text:
        for anchor_word, pathway in _BODY_REGION_PATHWAY_MAP.items():
            if anchor_word in body_region_text.split():
                return pathway

    return GENERAL_PATHWAY


# ── Discriminator Completion ─────────────────────────────────────────────────


def _is_discriminator_answered(
    discriminator: Discriminator,
    facts: ExtractedFacts,
) -> bool:
    """
    Check whether a discriminator has been answered.

    A discriminator is considered answered if any of its answer_signals
    appear in facts.associated_symptoms or facts.additional_context.

    Additionally, specific discriminators that map to top-level fact fields
    are also checked against those fields:
    - "fever_present"         → any symptom signal in associated_symptoms
    - "pregnancy_status"      → facts.is_pregnant is not None
    - "shortness_of_breath"   → already captured in associated_symptoms

    Args:
        discriminator: The discriminator to check.
        facts: Currently extracted clinical facts.

    Returns:
        True if the discriminator has been answered, False otherwise.
    """
    # Special case: pregnancy maps to the top-level is_pregnant field
    if discriminator.fact_key == "pregnancy_status":
        return facts.is_pregnant is not None

    # Build searchable text from symptom fields
    search_parts: list[str] = list(facts.associated_symptoms)
    if facts.denied_symptoms:
        search_parts.extend(facts.denied_symptoms)
    if facts.additional_context:
        search_parts.append(facts.additional_context)
    if facts.chief_complaint:
        search_parts.append(facts.chief_complaint)

    search_text = " ".join(search_parts).lower()

    for signal in discriminator.answer_signals:
        if signal.lower() in search_text:
            return True

    return False


def get_unanswered_discriminators(
    pathway: ClinicalPathway,
    facts: ExtractedFacts,
) -> list[Discriminator]:
    """
    Return pathway discriminators that have not yet been answered.

    Preserves the pathway-defined order — the first item in the returned
    list is the highest-priority question to ask next.

    Args:
        pathway: The active clinical pathway.
        facts: Currently extracted clinical facts.

    Returns:
        Ordered list of unanswered Discriminator objects.
    """
    return [
        disc
        for disc in pathway.discriminators
        if not _is_discriminator_answered(disc, facts)
    ]
