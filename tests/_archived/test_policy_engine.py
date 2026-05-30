"""
Policy engine unit tests.

Tests the decision logic for determining next actions
based on facts, rules, and turn count.
"""

import pytest

from app.engine.clinical_pathways import CARDIAC_PATHWAY, GENERAL_PATHWAY, NEUROLOGICAL_PATHWAY
from app.engine.policy_engine import compute_recommendation, decide_next_action, _get_missing_facts
from app.engine.safety_rules import SafetyRuleMatch
from app.schemas.enums import Specialty, Urgency
from app.schemas.fact import ExtractedFacts


class TestMissingFacts:
    """Tests for missing fact detection."""

    def test_all_missing_when_empty(self):
        facts = ExtractedFacts()
        missing, _, _ = _get_missing_facts(facts)
        assert "chief_complaint" in missing
        # Baseline facts are not added until chief_complaint is known
        # (they appear after pathway discriminators in priority order)

    def test_chief_complaint_always_first_when_missing(self):
        facts = ExtractedFacts()
        missing, _, _ = _get_missing_facts(facts)
        assert missing[0] == "chief_complaint"

    def test_none_missing_when_complete_no_pathway_discriminators(self):
        """A 'feeling tired' complaint matches GENERAL pathway (no discriminators)."""
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=30,
            sex="male",
            duration="3 days",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        assert len(missing) == 0

    def test_partial_facts(self):
        facts = ExtractedFacts(chief_complaint="feeling tired", age=30)
        missing, _, _ = _get_missing_facts(facts)
        assert "chief_complaint" not in missing
        assert "age" not in missing
        assert "sex" in missing
        assert "duration" in missing

    def test_pregnancy_asked_for_female_of_age(self):
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=25,
            sex="female",
            duration="1 week",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        assert "is_pregnant" in missing

    def test_pregnancy_not_asked_for_male(self):
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=25,
            sex="male",
            duration="1 week",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        assert "is_pregnant" not in missing

    def test_pregnancy_not_asked_for_child(self):
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=8,
            sex="female",
            duration="1 week",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        assert "is_pregnant" not in missing

    def test_pregnancy_not_asked_for_older_female(self):
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=60,
            sex="female",
            duration="1 week",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        assert "is_pregnant" not in missing


class TestDecideNextAction:
    """Tests for the main decision function."""

    def test_emergency_overrides_all(self):
        facts = ExtractedFacts()
        emergency_match = SafetyRuleMatch(
            rule_id="RF-001",
            rule_name="Chest pain with shortness of breath",
            severity="emergency",
            evidence_snippet="chest pain, shortness of breath",
        )
        decision = decide_next_action(facts, [emergency_match], turn_count=1)
        assert decision.action == "escalate"
        assert decision.urgency == Urgency.EMERGENCY
        assert decision.specialty == Specialty.EMERGENCY_DEPARTMENT

    def test_ask_when_facts_missing(self):
        facts = ExtractedFacts(chief_complaint="headache")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.action == "ask"
        assert len(decision.missing_facts) > 0

    def test_complete_when_facts_complete_general_pathway(self):
        """For a GENERAL pathway complaint, complete once baseline facts are present."""
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=30,
            sex="male",
            duration="3 days",
            severity="moderate",
        )
        decision = decide_next_action(facts, [], turn_count=3)
        assert decision.action == "complete"

    def test_turn_limit_forces_completion(self):
        facts = ExtractedFacts(chief_complaint="pain")
        decision = decide_next_action(facts, [], turn_count=8)
        assert decision.action == "complete"
        assert decision.specialty == Specialty.GENERAL_PRACTITIONER
        assert decision.confidence < 0.5

    def test_first_missing_fact_is_chief_complaint(self):
        facts = ExtractedFacts()
        decision = decide_next_action(facts, [], turn_count=0)
        assert decision.action == "ask"
        # chief_complaint should be the highest-priority missing fact
        assert decision.missing_facts[0] == "chief_complaint"


class TestPathwayAwarePriority:
    """Tests that verify pathway discriminators are asked before baseline facts."""

    def test_chest_pain_asks_sob_before_age(self):
        """With chief_complaint='chest pain', SOB must come before age."""
        facts = ExtractedFacts(chief_complaint="chest pain")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.action == "ask"
        assert decision.missing_facts[0] == "shortness_of_breath", (
            f"Expected 'shortness_of_breath' first, got: {decision.missing_facts[0]!r}"
        )
        # Verify age is present but behind discriminators
        assert "age" in decision.missing_facts
        age_idx = decision.missing_facts.index("age")
        sob_idx = decision.missing_facts.index("shortness_of_breath")
        assert sob_idx < age_idx

    def test_headache_asks_vision_before_age(self):
        """With chief_complaint='headache', vision_changes must come before age."""
        facts = ExtractedFacts(chief_complaint="headache")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.action == "ask"
        assert decision.missing_facts[0] == "vision_changes", (
            f"Expected 'vision_changes' first, got: {decision.missing_facts[0]!r}"
        )

    def test_urdu_seenay_dard_asks_sob_first(self):
        """Roman Urdu chest pain complaint should still trigger CARDIAC pathway."""
        facts = ExtractedFacts(chief_complaint="seenay mein dard")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.missing_facts[0] == "shortness_of_breath"
        assert decision.active_pathway == "CARDIAC"

    def test_generic_complaint_uses_flat_list(self):
        """Vague complaint → GENERAL pathway → flat baseline priority."""
        facts = ExtractedFacts(chief_complaint="feeling unwell")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.active_pathway == "GENERAL"
        # First missing should be a baseline fact (age, sex, etc.)
        assert decision.missing_facts[0] in ("age", "sex", "duration", "severity")

    def test_discriminators_come_before_baseline_facts(self):
        """Discriminators must all appear before any baseline facts."""
        facts = ExtractedFacts(chief_complaint="chest pain")
        missing, pathway, unanswered = _get_missing_facts(facts)
        disc_keys = {d.fact_key for d in pathway.discriminators}
        baseline_keys = {"age", "sex", "duration", "severity"}
        # Find the last discriminator position and first baseline position
        disc_positions = [i for i, k in enumerate(missing) if k in disc_keys]
        baseline_positions = [i for i, k in enumerate(missing) if k in baseline_keys]
        if disc_positions and baseline_positions:
            assert max(disc_positions) < min(baseline_positions), (
                "A discriminator appears after a baseline fact"
            )

    def test_answered_discriminator_not_in_missing(self):
        """Once SOB is answered, the next discriminator should be first."""
        facts = ExtractedFacts(
            chief_complaint="chest pain",
            associated_symptoms=["shortness of breath"],
        )
        decision = decide_next_action(facts, [], turn_count=1)
        assert "shortness_of_breath" not in decision.missing_facts
        # Next discriminator should now be first
        assert decision.missing_facts[0] == "radiating_pain"

    def test_active_pathway_set_in_decision(self):
        """active_pathway should be populated for known complaints."""
        facts = ExtractedFacts(chief_complaint="chest pain")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.active_pathway == "CARDIAC"

    def test_discriminator_context_set_for_pathway_question(self):
        """discriminator_context should be populated when asking a discriminator."""
        facts = ExtractedFacts(chief_complaint="chest pain")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.discriminator_context is not None
        assert len(decision.discriminator_context) > 0

    def test_discriminator_context_none_for_baseline_fact(self):
        """No discriminator_context when asking a baseline fact (GENERAL pathway)."""
        facts = ExtractedFacts(chief_complaint="feeling unwell")
        decision = decide_next_action(facts, [], turn_count=1)
        assert decision.discriminator_context is None

    def test_cardiac_urgency_bias_applied(self):
        """CARDIAC pathway urgency_bias (URGENT) should apply as floor."""
        facts = ExtractedFacts(
            chief_complaint="chest pain",
            age=40, sex="male", duration="1 day", severity="mild",
            associated_symptoms=["shortness of breath", "radiating to arm"],
            additional_context="came on suddenly",
        )
        from app.engine.clinical_pathways import match_pathway
        pathway = match_pathway(facts)
        _, urgency, _ = compute_recommendation(facts, pathway)
        # Even with mild severity, CARDIAC bias should push to at least URGENT
        assert urgency in (Urgency.URGENT, Urgency.EMERGENCY)

    def test_no_duplicate_pregnancy_fact(self):
        """is_pregnant should only appear once in missing even with GYNECOLOGICAL pathway."""
        facts = ExtractedFacts(
            chief_complaint="pelvic pain",
            age=28,
            sex="female",
            duration="1 week",
            severity="moderate",
        )
        missing, _, _ = _get_missing_facts(facts)
        pregnancy_count = missing.count("is_pregnant") + missing.count("pregnancy_status")
        assert pregnancy_count <= 1, "Pregnancy asked more than once"



class TestExtractedFactsMerge:
    """Tests for the incremental fact merge logic."""

    def test_merge_adds_new_facts(self):
        existing = ExtractedFacts(chief_complaint="headache")
        new = ExtractedFacts(age=30, sex="male")
        merged = existing.merge(new)
        assert merged.chief_complaint == "headache"
        assert merged.age == 30
        assert merged.sex == "male"

    def test_merge_does_not_erase(self):
        existing = ExtractedFacts(chief_complaint="headache", age=25)
        new = ExtractedFacts(age=None, sex="female")
        merged = existing.merge(new)
        assert merged.chief_complaint == "headache"
        assert merged.age == 25  # Not erased by None
        assert merged.sex == "female"

    def test_merge_extends_symptoms(self):
        existing = ExtractedFacts(associated_symptoms=["nausea"])
        new = ExtractedFacts(associated_symptoms=["vomiting", "nausea"])
        merged = existing.merge(new)
        assert "nausea" in merged.associated_symptoms
        assert "vomiting" in merged.associated_symptoms
        assert len(merged.associated_symptoms) == 2  # Deduped

    def test_merge_new_value_overrides(self):
        existing = ExtractedFacts(severity="mild")
        new = ExtractedFacts(severity="severe")
        merged = existing.merge(new)
        assert merged.severity == "severe"


class TestComputeRecommendation:
    """Tests for the specialty mapping engine (FR-04.4)."""

    def test_gastroenterologist_stomach_pain(self):
        facts = ExtractedFacts(
            chief_complaint="stomach pain after meals with nausea",
            age=32, sex="male", duration="3 days", severity="moderate",
            associated_symptoms=["nausea", "bloating"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.GASTROENTEROLOGIST
        assert urgency == Urgency.ROUTINE

    def test_dermatologist_skin_rash(self):
        facts = ExtractedFacts(
            chief_complaint="skin rash on arms",
            age=28, sex="female", duration="2 weeks", severity="mild",
            associated_symptoms=["itching"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.DERMATOLOGIST

    def test_ent_ear_pain(self):
        facts = ExtractedFacts(
            chief_complaint="ear pain and hearing loss",
            age=45, sex="male", duration="1 week", severity="moderate",
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.ENT

    def test_pulmonologist_cough(self):
        facts = ExtractedFacts(
            chief_complaint="persistent cough and wheezing",
            age=50, sex="male", duration="1 month", severity="moderate",
            associated_symptoms=["wheezing"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.PULMONOLOGIST

    def test_orthopedist_joint_pain(self):
        facts = ExtractedFacts(
            chief_complaint="joint pain and swelling in knees",
            age=55, sex="female", duration="3 weeks", severity="moderate",
            associated_symptoms=["swelling"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.ORTHOPEDIST

    def test_neurologist_headache(self):
        facts = ExtractedFacts(
            chief_complaint="persistent headaches with blurred vision",
            age=40, sex="male", duration="2 weeks", severity="severe",
            associated_symptoms=["blurred vision"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.NEUROLOGIST

    def test_urologist_urinary(self):
        facts = ExtractedFacts(
            chief_complaint="painful urination with blood in urine",
            age=35, sex="male", duration="5 days", severity="moderate",
            associated_symptoms=["blood in urine"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.UROLOGIST

    def test_psychiatrist_mental_health(self):
        facts = ExtractedFacts(
            chief_complaint="anxiety and insomnia",
            age=30, sex="female", duration="2 months", severity="moderate",
            associated_symptoms=["insomnia", "stress"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.PSYCHIATRIST

    def test_gynecologist_menstrual(self):
        facts = ExtractedFacts(
            chief_complaint="irregular periods with pelvic pain",
            age=28, sex="female", duration="3 months", severity="moderate",
            associated_symptoms=["pelvic pain"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.GYNECOLOGIST

    def test_pediatrician_child(self):
        facts = ExtractedFacts(
            chief_complaint="mild fever and cough",
            age=5, sex="male", duration="2 days", severity="mild",
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.PEDIATRICIAN

    def test_gp_fallback_vague_symptoms(self):
        facts = ExtractedFacts(
            chief_complaint="feeling unwell",
            age=40, sex="male", duration="1 day", severity="mild",
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.GENERAL_PRACTITIONER

    def test_roman_urdu_pet_dard(self):
        facts = ExtractedFacts(
            chief_complaint="pet mein dard hai aur ulti",
            age=30, sex="male", duration="2 din", severity="moderate",
            associated_symptoms=["ulti"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.GASTROENTEROLOGIST

    def test_roman_urdu_sar_dard(self):
        facts = ExtractedFacts(
            chief_complaint="shadeed sar dard aur chakkar",
            age=35, sex="female", duration="1 hafta", severity="severe",
            associated_symptoms=["chakkar"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.NEUROLOGIST

    def test_roman_urdu_jild(self):
        facts = ExtractedFacts(
            chief_complaint="jild par daane aur khujli",
            age=22, sex="male", duration="2 hafta", severity="mild",
            associated_symptoms=["khujli"],
        )
        specialty, urgency, confidence = compute_recommendation(facts)
        assert specialty == Specialty.DERMATOLOGIST


class TestUrgencyModifiers:
    """Tests for urgency computation modifiers."""

    def test_severe_bumps_to_urgent(self):
        facts = ExtractedFacts(
            chief_complaint="headache", age=30, sex="male",
            duration="3 days", severity="severe",
        )
        _, urgency, _ = compute_recommendation(facts)
        assert urgency == Urgency.URGENT

    def test_long_duration_bumps_to_urgent(self):
        facts = ExtractedFacts(
            chief_complaint="cough and wheezing",
            age=40, sex="male", duration="1 month", severity="moderate",
        )
        _, urgency, _ = compute_recommendation(facts)
        assert urgency == Urgency.URGENT

    def test_blood_in_symptoms_is_urgent(self):
        facts = ExtractedFacts(
            chief_complaint="painful urination",
            age=35, sex="male", duration="3 days", severity="moderate",
            associated_symptoms=["blood in urine"],
        )
        _, urgency, _ = compute_recommendation(facts)
        assert urgency == Urgency.URGENT

    def test_child_fever_is_urgent(self):
        facts = ExtractedFacts(
            chief_complaint="fever and not eating",
            age=3, sex="male", duration="1 day", severity="moderate",
        )
        _, urgency, _ = compute_recommendation(facts)
        assert urgency == Urgency.URGENT

    def test_mild_short_duration_is_routine(self):
        facts = ExtractedFacts(
            chief_complaint="skin rash",
            age=25, sex="female", duration="2 days", severity="mild",
        )
        _, urgency, _ = compute_recommendation(facts)
        assert urgency == Urgency.ROUTINE


class TestConfidenceScoring:
    """Tests for confidence score computation."""

    def test_high_confidence_multiple_keyword_matches(self):
        facts = ExtractedFacts(
            chief_complaint="stomach pain with nausea bloating and vomiting",
            age=30, sex="male", duration="3 days", severity="moderate",
        )
        _, _, confidence = compute_recommendation(facts)
        assert confidence >= 0.9

    def test_low_confidence_no_clear_match(self):
        facts = ExtractedFacts(
            chief_complaint="feeling tired",
            age=40, sex="male", duration="1 week", severity="mild",
        )
        _, _, confidence = compute_recommendation(facts)
        assert confidence < 0.7

    def test_missing_chief_complaint_reduces_confidence(self):
        facts = ExtractedFacts(
            age=30, sex="male", duration="3 days", severity="moderate",
        )
        _, _, confidence = compute_recommendation(facts)
        assert confidence < 0.7  # penalized for missing chief complaint


class TestDurationParsing:
    """Tests for the duration string parser."""

    def test_parse_days(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("3 days") == 3

    def test_parse_weeks(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("2 weeks") == 14

    def test_parse_months(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("1 month") == 30

    def test_parse_urdu_din(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("3 din") == 3

    def test_parse_urdu_hafta(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("1 hafta") == 7

    def test_parse_none(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days(None) is None

    def test_parse_unparseable(self):
        from app.engine.policy_engine import _parse_duration_days
        assert _parse_duration_days("a long time") is None
