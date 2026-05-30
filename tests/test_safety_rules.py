"""
Safety rules unit tests.

Exhaustive tests for all 10 red-flag rules (PRD §8) in both English
and Roman Urdu. Ensures zero false negatives (NFR-03).
"""

import pytest

from app.engine.safety_rules import (
    SafetyRuleMatch,
    check_safety_rules,
    has_emergency,
    has_urgent,
)
from app.schemas.fact import ExtractedFacts


# ── RF-001: Chest pain + shortness of breath ─────────────────────────────


class TestRF001:
    """Chest pain with shortness of breath → Emergency."""

    def test_english_triggers(self):
        matches = check_safety_rules("I have chest pain and shortness of breath")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_english_variant(self):
        matches = check_safety_rules("my chest hurts and I can't breathe")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_roman_urdu_triggers(self):
        matches = check_safety_rules("seenay mein dard hai aur saans lene mein takleef ho rahi hai")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_roman_urdu_variant(self):
        matches = check_safety_rules("seene mein dard hai aur saans nahi aa rahi")
        assert has_emergency(matches)

    def test_chest_pain_alone_no_trigger(self):
        """Chest pain without breathing issues should NOT trigger RF-001."""
        matches = check_safety_rules("I have chest pain")
        rf001 = [m for m in matches if m.rule_id == "RF-001"]
        assert len(rf001) == 0

    def test_breathing_alone_no_trigger(self):
        """Breathing issues alone should NOT trigger RF-001."""
        matches = check_safety_rules("I have shortness of breath")
        rf001 = [m for m in matches if m.rule_id == "RF-001"]
        assert len(rf001) == 0

    def test_mixed_language(self):
        matches = check_safety_rules("meri chest mein dard hai and I can't breathe properly")
        assert has_emergency(matches)


# ── RF-002: Severe bleeding ──────────────────────────────────────────────


class TestRF002:
    """Severe or uncontrolled bleeding → Emergency."""

    def test_english_severe_bleeding(self):
        matches = check_safety_rules("I'm having severe bleeding from my arm")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-002" for m in matches)

    def test_english_wont_stop(self):
        matches = check_safety_rules("the blood won't stop flowing")
        assert has_emergency(matches)

    def test_roman_urdu(self):
        matches = check_safety_rules("bohat khoon aa raha hai")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-002" for m in matches)

    def test_roman_urdu_variant(self):
        matches = check_safety_rules("khoon band nahi ho raha hai")
        assert has_emergency(matches)

    def test_normal_bleeding_no_trigger(self):
        """Mild bleeding mention should not trigger — only severe/uncontrolled."""
        matches = check_safety_rules("I had a small cut and it bled a little")
        rf002 = [m for m in matches if m.rule_id == "RF-002"]
        assert len(rf002) == 0


# ── RF-003: Loss of consciousness ────────────────────────────────────────


class TestRF003:
    """Loss of consciousness → Emergency."""

    def test_english_unconscious(self):
        matches = check_safety_rules("my father is unconscious")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-003" for m in matches)

    def test_english_fainted(self):
        matches = check_safety_rules("I fainted at work today")
        assert has_emergency(matches)

    def test_english_passed_out(self):
        matches = check_safety_rules("she passed out and hasn't woken up")
        assert has_emergency(matches)

    def test_roman_urdu(self):
        matches = check_safety_rules("mere bhai ko hosh nahi hai")
        assert has_emergency(matches)

    def test_roman_urdu_behosh(self):
        matches = check_safety_rules("patient behosh ho gaya")
        assert has_emergency(matches)


# ── RF-004: Suicidal ideation / self-harm ─────────────────────────────────


class TestRF004:
    """Suicidal ideation → Emergency + crisis info."""

    def test_english_suicidal(self):
        matches = check_safety_rules("I am feeling suicidal")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-004" for m in matches)

    def test_english_want_to_die(self):
        matches = check_safety_rules("I just want to die")
        assert has_emergency(matches)
        match = next(m for m in matches if m.rule_id == "RF-004")
        assert match.crisis_info is not None
        assert "Umang" in match.crisis_info

    def test_english_self_harm(self):
        matches = check_safety_rules("I've been thinking about self-harm")
        assert has_emergency(matches)

    def test_roman_urdu(self):
        matches = check_safety_rules("marna chahta hoon")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-004" for m in matches)

    def test_roman_urdu_khudkushi(self):
        matches = check_safety_rules("khudkushi ka soch raha hoon")
        assert has_emergency(matches)

    def test_crisis_info_present(self):
        matches = check_safety_rules("I want to kill myself")
        match = next(m for m in matches if m.rule_id == "RF-004")
        assert "0311-7786264" in match.crisis_info  # Umang helpline
        assert "0316-8275336" in match.crisis_info  # Taskeen helpline


# ── RF-005: Stroke signs ─────────────────────────────────────────────────


class TestRF005:
    """Stroke signs (2+ matching groups) → Emergency."""

    def test_english_numbness_and_speech(self):
        matches = check_safety_rules("sudden numbness on one side and slurred speech")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-005" for m in matches)

    def test_english_vision_and_headache(self):
        matches = check_safety_rules("sudden vision loss and worst headache of my life")
        assert has_emergency(matches)

    def test_single_symptom_no_trigger(self):
        """Only one stroke sign should NOT trigger (need 2+)."""
        matches = check_safety_rules("I have slurred speech")
        rf005 = [m for m in matches if m.rule_id == "RF-005"]
        assert len(rf005) == 0

    def test_roman_urdu(self):
        matches = check_safety_rules("achanak sunn ho gaya aur bol nahi pa raha")
        assert has_emergency(matches)


# ── RF-006: Severe allergic reaction ──────────────────────────────────────


class TestRF006:
    """Severe allergic reaction (2+ matching groups) → Emergency."""

    def test_english_throat_and_breathing(self):
        matches = check_safety_rules("my throat is swelling and I can't breathe")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-006" for m in matches)

    def test_english_face_and_breathing(self):
        matches = check_safety_rules("my face is swollen and I have difficulty breathing")
        assert has_emergency(matches)

    def test_single_symptom_no_trigger(self):
        matches = check_safety_rules("my face is swollen")
        rf006 = [m for m in matches if m.rule_id == "RF-006"]
        assert len(rf006) == 0

    def test_roman_urdu(self):
        matches = check_safety_rules("gala suj gaya hai aur saans nahi aa rahi")
        assert has_emergency(matches)


# ── RF-007: Severe abdominal pain + fever + vomiting ──────────────────────


class TestRF007:
    """Severe abdominal pain + fever + vomiting → Urgent (not emergency)."""

    def test_english_all_three(self):
        matches = check_safety_rules("I have severe stomach pain with fever and I'm throwing up")
        assert has_urgent(matches)
        match = next(m for m in matches if m.rule_id == "RF-007")
        assert match.severity == "urgent"

    def test_roman_urdu_all_three(self):
        matches = check_safety_rules("shadeed pet dard hai bukhar bhi hai aur ulti ho rahi hai")
        assert has_urgent(matches)

    def test_missing_one_no_trigger(self):
        """Missing one of the three should not trigger."""
        matches = check_safety_rules("severe stomach pain and fever")
        rf007 = [m for m in matches if m.rule_id == "RF-007"]
        assert len(rf007) == 0


# ── RF-008: High fever in child under 5 ──────────────────────────────────


class TestRF008:
    """High fever (>104°F) in child under 5 → Emergency (requires fact check)."""

    def test_with_child_facts(self):
        facts = ExtractedFacts(age=3)
        matches = check_safety_rules("my child has a very high fever of 105", facts)
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-008" for m in matches)

    def test_without_child_facts_no_trigger(self):
        """Without age fact, cannot trigger (fact check fails)."""
        matches = check_safety_rules("my child has a very high fever of 105")
        rf008 = [m for m in matches if m.rule_id == "RF-008"]
        assert len(rf008) == 0

    def test_adult_no_trigger(self):
        """Adult with high fever should NOT trigger RF-008."""
        facts = ExtractedFacts(age=30)
        matches = check_safety_rules("I have a very high fever of 105", facts)
        rf008 = [m for m in matches if m.rule_id == "RF-008"]
        assert len(rf008) == 0

    def test_roman_urdu_with_facts(self):
        facts = ExtractedFacts(age=2)
        matches = check_safety_rules("bachay ko bohat tez bukhar hai 104 se zyada", facts)
        assert has_emergency(matches)


# ── RF-009: Seizure / convulsion ──────────────────────────────────────────


class TestRF009:
    """Seizure / convulsion → Emergency."""

    def test_english_seizure(self):
        matches = check_safety_rules("my son is having a seizure")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-009" for m in matches)

    def test_english_convulsion(self):
        matches = check_safety_rules("she is having convulsions")
        assert has_emergency(matches)

    def test_roman_urdu_dora(self):
        matches = check_safety_rules("bachay ko dora para hai")
        assert has_emergency(matches)

    def test_roman_urdu_mirgi(self):
        matches = check_safety_rules("mirgi ka dora aa gaya")
        assert has_emergency(matches)


# ── RF-010: Pregnancy bleeding / severe pain ──────────────────────────────


class TestRF010:
    """Pregnancy-related bleeding or severe pain → Emergency."""

    def test_english_pregnant_bleeding(self):
        matches = check_safety_rules("I am pregnant and I'm bleeding")
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-010" for m in matches)

    def test_english_pregnancy_pain(self):
        matches = check_safety_rules("I'm pregnant and having severe pain")
        assert has_emergency(matches)

    def test_roman_urdu(self):
        matches = check_safety_rules("hamal mein khoon aa raha hai")
        assert has_emergency(matches)

    def test_not_pregnant_no_trigger(self):
        """Bleeding alone without pregnancy context should NOT trigger RF-010."""
        matches = check_safety_rules("I have bleeding")
        rf010 = [m for m in matches if m.rule_id == "RF-010"]
        assert len(rf010) == 0


# ── Cross-cutting Tests ──────────────────────────────────────────────────


class TestCrossCutting:
    """Tests for general safety rule behavior."""

    def test_case_insensitive(self):
        matches = check_safety_rules("I HAVE CHEST PAIN AND SHORTNESS OF BREATH")
        assert has_emergency(matches)

    def test_no_false_positives_normal_text(self):
        """Normal symptom descriptions should not trigger emergency rules."""
        matches = check_safety_rules("I have a mild headache")
        assert not has_emergency(matches)

    def test_no_false_positives_common_text(self):
        matches = check_safety_rules("my stomach hurts a little after meals")
        assert not has_emergency(matches)

    def test_multiple_rules_can_trigger(self):
        """A single message can trigger multiple rules."""
        matches = check_safety_rules(
            "I am pregnant and bleeding and I have chest pain and can't breathe"
        )
        rule_ids = {m.rule_id for m in matches}
        assert "RF-001" in rule_ids  # chest + breathing
        assert "RF-010" in rule_ids  # pregnant + bleeding

    def test_empty_input_no_crash(self):
        matches = check_safety_rules("")
        assert len(matches) == 0

    def test_whitespace_only_no_crash(self):
        matches = check_safety_rules("   \n\t  ")
        assert len(matches) == 0


# ── Normalized Text Tests ────────────────────────────────────────────────


class TestNormalizedText:
    """
    Tests for the normalized_text parameter (semantic gap fix).

    These tests simulate what happens when the LLM normalizer translates a
    colloquial or Roman Urdu phrase into canonical clinical terms that the
    keyword rules can then match.
    """

    # --- Backward compatibility: existing behaviour is unchanged ---

    def test_raw_match_still_works_without_normalized(self):
        """Raw keyword matching must work exactly as before (no regression)."""
        matches = check_safety_rules(
            "I have chest pain and shortness of breath"
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_normalized_none_behaves_like_before(self):
        """Passing normalized_text=None is identical to the original call."""
        without_norm = check_safety_rules("I have chest pain and shortness of breath")
        with_none = check_safety_rules(
            "I have chest pain and shortness of breath", normalized_text=None
        )
        assert {m.rule_id for m in without_norm} == {m.rule_id for m in with_none}

    def test_raw_still_checked_when_normalized_provided(self):
        """When normalized_text is provided, raw text is still checked too."""
        # Raw text matches RF-001 even though normalized text is neutral
        matches = check_safety_rules(
            raw_text="chest pain and can't breathe",
            normalized_text="some unrelated clinical terms",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    # --- Core semantic gap scenarios ---

    def test_heart_pain_via_normalization_triggers_rf001(self):
        """
        'heart pain' alone does not match any RF-001 keyword.
        After normalization to 'chest pain, difficulty breathing' it must trigger.
        This is the canonical bug this fix resolves.
        """
        # Raw text alone — should NOT trigger RF-001
        raw_matches = check_safety_rules("my heart is hurting and I cannot breathe well")
        # (may or may not trigger depending on existing keywords; we focus on
        #  the normalized path so we specifically test a phrase with no raw match)
        truly_raw = check_safety_rules("heart pain breathing problem")
        rf001_raw = [m for m in truly_raw if m.rule_id == "RF-001"]
        assert len(rf001_raw) == 0, "Sanity: raw 'heart pain' alone should not match"

        # With normalization — MUST trigger RF-001
        matches = check_safety_rules(
            raw_text="heart pain breathing problem",
            normalized_text="chest pain, difficulty breathing, shortness of breath",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_dil_mein_dard_via_normalization_triggers_rf001(self):
        """'dil mein dard' (Roman Urdu for heart pain) should trigger RF-001 via normalization."""
        # Raw text: 'dil mein dard' has no RF-001 match
        raw_matches = check_safety_rules("dil mein dard aur saans nahi aa rahi")
        # Note: 'saans nahi aa rahi' IS in ur_patterns for RF-001 group 2,
        # but 'dil mein dard' is not in group 1 → should NOT trigger as AND rule.
        # The normalization adds 'chest pain' which satisfies group 1.
        matches = check_safety_rules(
            raw_text="dil mein dard aur saans nahi aa rahi",
            normalized_text="chest pain, difficulty breathing, shortness of breath",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_fits_colloquial_via_normalization_triggers_rf009(self):
        """'fits' colloquially triggers RF-009 via normalization to 'seizure'."""
        # Note: 'fit'/'fits' IS in the RF-009 keyword list, so this is also
        # a direct test; keep it as a normalization path sanity check too.
        matches = check_safety_rules(
            raw_text="my child had fits last night",
            normalized_text="seizure, convulsion, child",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-009" for m in matches)

    def test_want_it_to_end_via_normalization_triggers_rf004(self):
        """Indirect suicidal phrase triggers RF-004 after normalization."""
        # Raw text alone — does not match RF-004 keywords
        raw_matches = check_safety_rules("I want it all to end, I see no point")
        rf004_raw = [m for m in raw_matches if m.rule_id == "RF-004"]
        assert len(rf004_raw) == 0, "Sanity: indirect phrase should not match raw"

        # With normalization to canonical suicidal ideation term
        matches = check_safety_rules(
            raw_text="I want it all to end, I see no point",
            normalized_text="suicidal ideation, want to end life, no reason to live",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-004" for m in matches)

    def test_burning_chest_plus_breathing_via_normalization(self):
        """'burning feeling in my chest area' + 'hard to get air' → RF-001."""
        matches = check_safety_rules(
            raw_text="burning feeling in my chest area and hard to get air",
            normalized_text="chest pain, chest discomfort, difficulty breathing, shortness of breath",
        )
        assert has_emergency(matches)
        assert any(m.rule_id == "RF-001" for m in matches)

    def test_identical_raw_and_normalized_no_duplicate_match(self):
        """When raw == normalized, rules should not double-fire (still one result per rule)."""
        text = "I have chest pain and shortness of breath"
        matches = check_safety_rules(raw_text=text, normalized_text=text)
        rf001_matches = [m for m in matches if m.rule_id == "RF-001"]
        assert len(rf001_matches) == 1, "Rule must only fire once even with identical texts"

    def test_evidence_snippet_notes_normalization_source(self):
        """Evidence snippet should note '[via normalization]' when triggered by normalized text."""
        matches = check_safety_rules(
            raw_text="heart pain breathing problem",
            normalized_text="chest pain, difficulty breathing, shortness of breath",
        )
        rf001 = next((m for m in matches if m.rule_id == "RF-001"), None)
        assert rf001 is not None
        assert "via normalization" in rf001.evidence_snippet

    def test_rf007_via_normalization_high_temperature_throwing_up(self):
        """'high temperature' + 'throwing up' + 'bad stomach ache' → RF-007 via normalization."""
        matches = check_safety_rules(
            raw_text="bad stomach ache with high temperature and throwing up",
            normalized_text="severe abdominal pain, fever, vomiting",
        )
        assert has_urgent(matches)
        assert any(m.rule_id == "RF-007" for m in matches)

