"""
Deterministic safety rules engine (PRD §8, FR-03).

ALL red-flag detection lives here — entirely outside the LLM.
Rules are checked on EVERY user turn against both raw text and extracted facts.
False negatives are unacceptable (NFR-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.fact import ExtractedFacts


# ── Data Structures ───────────────────────────────────────────────────────


@dataclass
class SafetyRuleMatch:
    """Result of a triggered safety rule."""

    rule_id: str
    rule_name: str
    severity: str  # "emergency" | "urgent"
    evidence_snippet: str
    crisis_info: str | None = None


@dataclass
class PatternGroup:
    """A group of keyword patterns in one language."""

    keywords: list[str]


@dataclass
class SafetyRuleDefinition:
    """Definition of a single safety rule."""

    rule_id: str
    rule_name: str
    severity: str
    en_patterns: list[PatternGroup]
    ur_patterns: list[PatternGroup]
    combination: str  # "any", "all", "any_n"
    min_match: int = 1  # For "any_n" — how many groups must match
    fact_check: str | None = None  # Optional fact-based check function name
    crisis_info: str | None = None


# ── Rule Definitions (PRD §8) ────────────────────────────────────────────

SAFETY_RULES: list[SafetyRuleDefinition] = [
    # RF-001: Chest pain + shortness of breath → Emergency
    SafetyRuleDefinition(
        rule_id="RF-001",
        rule_name="Chest pain with shortness of breath",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=["chest pain", "pain in chest", "pain in my chest", "chest hurts", "chest tightness"]),
            PatternGroup(keywords=[
                "shortness of breath", "short of breath", "can't breathe",
                "cant breathe", "difficulty breathing", "hard to breathe",
                "trouble breathing", "breathing difficulty", "breathless",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "seenay mein dard", "seene mein dard", "chest mein dard",
                "chhati mein dard", "sine mein dard",
            ]),
            PatternGroup(keywords=[
                "saans lene mein takleef", "saans lene mein mushkil",
                "saans nahi aa rahi", "saans ki takleef",
                "dum ghutna", "dum ghut raha",
            ]),
        ],
        combination="all",
    ),
    # RF-002: Severe / uncontrolled bleeding → Emergency
    SafetyRuleDefinition(
        rule_id="RF-002",
        rule_name="Severe or uncontrolled bleeding",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=[
                "severe bleeding", "uncontrolled bleeding", "won't stop bleeding",
                "wont stop bleeding", "hemorrhage", "heavy bleeding",
                "bleeding profusely", "blood won't stop", "blood wont stop",
                "can't stop the bleeding", "cant stop the bleeding",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "bohat khoon", "bohut khoon", "khoon band nahi ho raha",
                "khoon nahi ruk raha", "bohat zyada khoon",
                "khoon beh raha hai", "shadeed khoon",
            ]),
        ],
        combination="any",
    ),
    # RF-003: Loss of consciousness → Emergency
    SafetyRuleDefinition(
        rule_id="RF-003",
        rule_name="Loss of consciousness",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=[
                "loss of consciousness", "lost consciousness", "unconscious",
                "fainted", "fainting", "passed out", "blacked out",
                "collapsed", "unresponsive",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "hosh nahi", "behosh", "be hosh", "gir gaya", "gir gayi",
                "hosh kho", "behoshi",
            ]),
        ],
        combination="any",
    ),
    # RF-004: Suicidal ideation / self-harm → Emergency + crisis info
    SafetyRuleDefinition(
        rule_id="RF-004",
        rule_name="Suicidal ideation or self-harm",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=[
                "suicidal", "suicide", "want to die", "kill myself",
                "end my life", "self-harm", "self harm", "harm myself",
                "don't want to live", "dont want to live",
                "want to end it", "no reason to live",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "marna chahta", "marna chahti", "khudkushi",
                "apne aap ko", "jeena nahi chahta", "jeena nahi chahti",
                "zindagi khatam", "mar jana chahta", "mar jana chahti",
            ]),
        ],
        combination="any",
        crisis_info=(
            "🆘 Crisis Helplines:\n"
            "• Umang Helpline: 0311-7786264\n"
            "• Taskeen Helpline: 0316-8275336\n"
            "• Emergency: 1122"
        ),
    ),
    # RF-005: Stroke signs → Emergency
    SafetyRuleDefinition(
        rule_id="RF-005",
        rule_name="Stroke signs",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=["sudden numbness", "suddenly numb", "face drooping", "face droop"]),
            PatternGroup(keywords=["slurred speech", "speech slurred", "can't speak", "cant speak", "trouble speaking"]),
            PatternGroup(keywords=["vision loss", "sudden vision", "can't see", "cant see", "lost vision", "blurred vision suddenly"]),
            PatternGroup(keywords=["severe headache"]),
        ],
        ur_patterns=[
            PatternGroup(keywords=["achanak sun", "achanak sunn"]),
            PatternGroup(keywords=["zuban ladkhadana", "bol nahi pa raha", "bol nahi pa rahi"]),
            PatternGroup(keywords=["nazar chali gayi", "dikhai nahi de raha", "nazar band"]),
            PatternGroup(keywords=["shadeed sar dard", "bohat tez sar dard"]),
        ],
        combination="any_n",
        min_match=2,
    ),
    # RF-011: Thunderclap headache (possible subarachnoid hemorrhage) → Emergency
    SafetyRuleDefinition(
        rule_id="RF-011",
        rule_name="Thunderclap headache",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=["worst headache", "thunderclap headache", "bolt of lightning", "worst pain in my head", "hit me all at once"]),
        ],
        ur_patterns=[
            PatternGroup(keywords=["zindagi ka sab se bura", "zindagi ka sab se shadeed sar dard", "bijli ki tarah", "achanak bohat tez dard"]),
        ],
        combination="any",
    ),
    # RF-006: Severe allergic reaction / anaphylaxis → Emergency
    SafetyRuleDefinition(
        rule_id="RF-006",
        rule_name="Severe allergic reaction / anaphylaxis",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=["throat swelling", "throat closing", "throat is closing", "swollen throat", "throat is swelling", "throat swollen"]),
            PatternGroup(keywords=[
                "can't breathe", "cant breathe", "difficulty breathing",
                "hard to breathe", "trouble breathing",
            ]),
            PatternGroup(keywords=["face swelling", "swollen face", "face is swollen", "lips swelling"]),
        ],
        ur_patterns=[
            PatternGroup(keywords=["gala sujan", "gala suj", "gala band"]),
            PatternGroup(keywords=["saans nahi aa rahi", "saans nahi", "dum ghutna"]),
            PatternGroup(keywords=["chehra sujan", "chehra suj", "hont suj"]),
        ],
        combination="any_n",
        min_match=2,
    ),
    # RF-007: Severe abdominal pain + fever + vomiting → Urgent
    SafetyRuleDefinition(
        rule_id="RF-007",
        rule_name="Severe abdominal pain with fever and vomiting",
        severity="urgent",
        en_patterns=[
            PatternGroup(keywords=["severe abdominal pain", "severe stomach pain", "intense stomach pain", "severe belly pain"]),
            PatternGroup(keywords=["fever", "high temperature", "febrile"]),
            PatternGroup(keywords=["vomiting", "throwing up", "vomit"]),
        ],
        ur_patterns=[
            PatternGroup(keywords=["shadeed pet dard", "bohat pet dard", "tez pet dard"]),
            PatternGroup(keywords=["bukhar", "tez bukhar"]),
            PatternGroup(keywords=["ulti", "qai"]),
        ],
        combination="all",
    ),
    # RF-008: High fever (>104°F / 40°C) in children under 5 → Emergency
    SafetyRuleDefinition(
        rule_id="RF-008",
        rule_name="High fever in child under 5",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=[
                "high fever", "very high fever", "104", "105", "106",
                "40 degree", "40.5", "41 degree",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "tez bukhar", "bohat tez bukhar", "104", "105",
                "40 degree",
            ]),
        ],
        combination="any",
        fact_check="child_under_5",
    ),
    # RF-009: Seizure / convulsion → Emergency
    SafetyRuleDefinition(
        rule_id="RF-009",
        rule_name="Seizure or convulsion",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=[
                "seizure", "seizures", "convulsion", "convulsions",
                "fit", "fits", "epileptic",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=[
                "dora", "dore", "mirgi", "jhatke", "jhatka",
            ]),
        ],
        combination="any",
    ),
    # RF-010: Pregnancy-related bleeding or severe pain → Emergency
    SafetyRuleDefinition(
        rule_id="RF-010",
        rule_name="Pregnancy-related bleeding or severe pain",
        severity="emergency",
        en_patterns=[
            PatternGroup(keywords=["pregnant", "pregnancy"]),
            PatternGroup(keywords=[
                "bleeding", "blood", "spotting",
                "severe pain", "intense pain", "sharp pain",
            ]),
        ],
        ur_patterns=[
            PatternGroup(keywords=["hamal", "pregnant", "hamla"]),
            PatternGroup(keywords=[
                "khoon", "khoon aa raha", "shadeed dard", "tez dard",
            ]),
        ],
        combination="all",
    ),
]


# ── Matching Logic ────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for consistent matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _group_matches(text: str, group: PatternGroup) -> bool:
    """Check if any keyword in the group matches within the text."""
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in group.keywords)


def _group_matches_any(texts: list[str], group: PatternGroup) -> bool:
    """Check if any keyword in the group matches within ANY of the provided texts.

    Used to run the same check against both raw and normalized text so that
    a match in either source triggers the rule (belt-and-suspenders).
    """
    return any(_group_matches(text, group) for text in texts if text)


def _check_fact_condition(
    fact_check: str, facts: ExtractedFacts | None
) -> bool:
    """Evaluate a fact-based condition."""
    if facts is None:
        return False

    if fact_check == "child_under_5":
        return facts.age is not None and facts.age < 5

    return False


def _evaluate_rule(
    rule: SafetyRuleDefinition,
    raw_history: str,
    facts: ExtractedFacts | None,
    normalized_text: str | None = None,
) -> SafetyRuleMatch | None:
    """
    Evaluate a single safety rule against raw history, normalized text, and facts.

    Belt-and-suspenders: each pattern group is tested against raw_history,
    normalized_text, and a facts_text string built from extracted facts.
    A group matches if it hits in ANY source. This ensures that:
    - Multi-turn emergencies trigger correctly (e.g. Turn 1: "chest pain", Turn 2: "shortness of breath").
    - Existing keyword matches are never lost (no regression).
    - Semantically equivalent phrases caught by normalization also trigger.

    Returns a SafetyRuleMatch if the rule triggers, None otherwise.
    """
    texts_to_check: list[str] = [raw_history]
    source_labels: list[str] = ["raw"]

    if normalized_text and normalized_text.strip().lower() != raw_history.strip().lower():
        texts_to_check.append(normalized_text)
        source_labels.append("normalized")

    # Build facts_text to catch keywords that were extracted in previous turns
    if facts:
        fact_parts = []
        if facts.chief_complaint: fact_parts.append(facts.chief_complaint)
        if facts.associated_symptoms: fact_parts.extend(facts.associated_symptoms)
        if facts.body_region: fact_parts.append(facts.body_region)
        facts_text = " ".join(fact_parts).strip().lower()
        if facts_text:
            texts_to_check.append(facts_text)
            source_labels.append("facts")

    # Combine all pattern groups from both languages
    all_groups = rule.en_patterns + rule.ur_patterns

    # Check which groups match (against any of the candidate texts)
    matched_groups: list[int] = []
    evidence_parts: list[str] = []
    match_sources: list[str] = []  # "raw", "normalized", or "facts" for audit

    for i, group in enumerate(all_groups):
        for source_label, text in zip(source_labels, texts_to_check):
            if _group_matches(text, group):
                matched_groups.append(i)
                # Find the specific keyword that matched for evidence
                normalized_for_scan = _normalize(text)
                for kw in group.keywords:
                    if kw in normalized_for_scan:
                        evidence_parts.append(kw)
                        match_sources.append(source_label)
                        break
                break  # Group matched — no need to check remaining texts

    # Apply combination logic
    triggered = False

    if rule.combination == "any":
        triggered = len(matched_groups) > 0
    elif rule.combination == "all":
        # All pattern groups (per language) must match. We check each language
        # set independently — if ALL groups in either language match, it triggers.
        en_count = sum(1 for i in matched_groups if i < len(rule.en_patterns))
        ur_count = sum(1 for i in matched_groups if i >= len(rule.en_patterns))
        triggered = (
            (len(rule.en_patterns) > 0 and en_count == len(rule.en_patterns))
            or (len(rule.ur_patterns) > 0 and ur_count == len(rule.ur_patterns))
        )
        # Also check cross-language: user might use mixed EN/UR
        if not triggered:
            total_unique_concepts = max(len(rule.en_patterns), len(rule.ur_patterns))
            triggered = len(matched_groups) >= total_unique_concepts
    elif rule.combination == "any_n":
        triggered = len(matched_groups) >= rule.min_match

    # Handle fact-based constraints
    if triggered and rule.fact_check:
        triggered = _check_fact_condition(rule.fact_check, facts)

    if not triggered:
        return None

    # Build evidence snippet, noting if normalization contributed
    if evidence_parts:
        evidence = ", ".join(evidence_parts)
        if "normalized" in match_sources:
            evidence += " [via normalization]"
        if "facts" in match_sources:
            evidence += " [via facts]"
    else:
        evidence = raw_history[:200]

    return SafetyRuleMatch(
        rule_id=rule.rule_id,
        rule_name=rule.rule_name,
        severity=rule.severity,
        evidence_snippet=evidence,
        crisis_info=rule.crisis_info,
    )


# ── Public API ────────────────────────────────────────────────────────────


def check_safety_rules(
    raw_text: str,
    facts: ExtractedFacts | None = None,
    normalized_text: str | None = None,
) -> list[SafetyRuleMatch]:
    """
    Run ALL safety rules against the raw user history, normalized text, and facts.

    Called on EVERY user turn (FR-03.1). Returns a list of all triggered rules.
    An empty list means no safety concerns were detected.

    Args:
        raw_text: The concatenated user message history (always checked).
        facts: Structured facts extracted from previous turns.
        normalized_text: Optional LLM-normalized clinical text for the current turn.
    """
    matches: list[SafetyRuleMatch] = []

    for rule in SAFETY_RULES:
        match = _evaluate_rule(rule, raw_text, facts, normalized_text)
        if match is not None:
            matches.append(match)

    return matches


def has_emergency(matches: list[SafetyRuleMatch]) -> bool:
    """Check if any of the matched rules are emergency-severity."""
    return any(m.severity == "emergency" for m in matches)


def has_urgent(matches: list[SafetyRuleMatch]) -> bool:
    """Check if any of the matched rules are urgent-severity."""
    return any(m.severity == "urgent" for m in matches)
