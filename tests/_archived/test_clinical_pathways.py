"""
Unit tests for clinical_pathways.py

Tests cover:
- Pathway matching for all 8 pathways (EN + Roman Urdu keywords)
- General fallback for unrecognised complaints
- Discriminator completion detection
- Pathway matching using secondary fields (body_region, associated_symptoms)
"""

from __future__ import annotations

import pytest

from app.engine.clinical_pathways import (
    ABDOMINAL_PATHWAY,
    CARDIAC_PATHWAY,
    GENERAL_PATHWAY,
    GYNECOLOGICAL_PATHWAY,
    MENTAL_HEALTH_PATHWAY,
    MUSCULOSKELETAL_PATHWAY,
    NEUROLOGICAL_PATHWAY,
    RESPIRATORY_PATHWAY,
    UROLOGICAL_PATHWAY,
    get_unanswered_discriminators,
    match_pathway,
)
from app.schemas.fact import ExtractedFacts


# ── Helpers ───────────────────────────────────────────────────────────────────


def facts_with_complaint(complaint: str, **kwargs) -> ExtractedFacts:
    return ExtractedFacts(chief_complaint=complaint, **kwargs)


def facts_with_symptoms(complaint: str, symptoms: list[str]) -> ExtractedFacts:
    return ExtractedFacts(chief_complaint=complaint, associated_symptoms=symptoms)


# ── Pathway Matching — English ─────────────────────────────────────────────────


class TestPathwayMatchingEnglish:
    def test_cardiac_chest_pain(self):
        f = facts_with_complaint("chest pain")
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_cardiac_heart_pain(self):
        f = facts_with_complaint("I have heart pain since yesterday")
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_cardiac_chest_pressure(self):
        f = facts_with_complaint("chest pressure when I walk")
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_neurological_headache(self):
        f = facts_with_complaint("bad headache for 2 days")
        assert match_pathway(f).pathway_id == "NEUROLOGICAL"

    def test_neurological_dizziness(self):
        f = facts_with_complaint("feeling very dizzy")
        assert match_pathway(f).pathway_id == "NEUROLOGICAL"

    def test_neurological_numbness(self):
        f = facts_with_complaint("numbness in my hand")
        assert match_pathway(f).pathway_id == "NEUROLOGICAL"

    def test_abdominal_stomach_pain(self):
        f = facts_with_complaint("stomach pain")
        assert match_pathway(f).pathway_id == "ABDOMINAL"

    def test_abdominal_nausea(self):
        f = facts_with_complaint("nausea and vomiting")
        assert match_pathway(f).pathway_id == "ABDOMINAL"

    def test_respiratory_cough(self):
        f = facts_with_complaint("cough for 3 weeks")
        assert match_pathway(f).pathway_id == "RESPIRATORY"

    def test_respiratory_breathing(self):
        f = facts_with_complaint("difficulty breathing at night")
        assert match_pathway(f).pathway_id == "RESPIRATORY"

    def test_gynecological_periods(self):
        f = facts_with_complaint("irregular periods")
        assert match_pathway(f).pathway_id == "GYNECOLOGICAL"

    def test_gynecological_pelvic_pain(self):
        f = facts_with_complaint("pelvic pain")
        assert match_pathway(f).pathway_id == "GYNECOLOGICAL"

    def test_urological_urination(self):
        f = facts_with_complaint("painful urination")
        assert match_pathway(f).pathway_id == "UROLOGICAL"

    def test_urological_kidney_stone(self):
        f = facts_with_complaint("I think I have kidney stone")
        assert match_pathway(f).pathway_id == "UROLOGICAL"

    def test_musculoskeletal_joint_pain(self):
        f = facts_with_complaint("joint pain in my knee")
        assert match_pathway(f).pathway_id == "MUSCULOSKELETAL"

    def test_musculoskeletal_back_pain(self):
        f = facts_with_complaint("severe back pain")
        assert match_pathway(f).pathway_id == "MUSCULOSKELETAL"

    def test_mental_health_anxiety(self):
        f = facts_with_complaint("anxiety and panic attacks")
        assert match_pathway(f).pathway_id == "MENTAL_HEALTH"

    def test_mental_health_depression(self):
        f = facts_with_complaint("feeling depressed and hopeless")
        assert match_pathway(f).pathway_id == "MENTAL_HEALTH"

    def test_general_fallback_vague(self):
        f = facts_with_complaint("just feeling unwell")
        assert match_pathway(f).pathway_id == "GENERAL"

    def test_general_fallback_fatigue(self):
        f = facts_with_complaint("tired all the time")
        assert match_pathway(f).pathway_id == "GENERAL"


# ── Pathway Matching — Roman Urdu ─────────────────────────────────────────────


class TestPathwayMatchingUrdu:
    def test_cardiac_seenay_mein_dard(self):
        f = facts_with_complaint("seenay mein dard ho raha hai")
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_cardiac_dil_mein_dard(self):
        f = facts_with_complaint("dil mein dard hai")
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_neurological_sar_dard(self):
        f = facts_with_complaint("sar dard bahut shadeed hai")
        assert match_pathway(f).pathway_id == "NEUROLOGICAL"

    def test_neurological_chakkar(self):
        f = facts_with_complaint("chakkar aa rahe hain")
        assert match_pathway(f).pathway_id == "NEUROLOGICAL"

    def test_abdominal_pet_dard(self):
        f = facts_with_complaint("pet dard aur ulti")
        assert match_pathway(f).pathway_id == "ABDOMINAL"

    def test_respiratory_khansi(self):
        f = facts_with_complaint("khansi nahi ruk rahi")
        assert match_pathway(f).pathway_id == "RESPIRATORY"

    def test_respiratory_saans(self):
        f = facts_with_complaint("saans lene mein mushkil")
        assert match_pathway(f).pathway_id == "RESPIRATORY"

    def test_gynecological_mahwari(self):
        f = facts_with_complaint("mahwari mein masla hai")
        assert match_pathway(f).pathway_id == "GYNECOLOGICAL"

    def test_urological_peshab(self):
        f = facts_with_complaint("peshab mein jalan hai")
        assert match_pathway(f).pathway_id == "UROLOGICAL"

    def test_musculoskeletal_kamar_dard(self):
        f = facts_with_complaint("kamar dard bohat zyada hai")
        assert match_pathway(f).pathway_id == "MUSCULOSKELETAL"

    def test_musculoskeletal_jor_dard(self):
        f = facts_with_complaint("jor dard aur sujan")
        assert match_pathway(f).pathway_id == "MUSCULOSKELETAL"

    def test_mental_health_neend(self):
        f = facts_with_complaint("neend nahi aati pareshani rehti hai")
        assert match_pathway(f).pathway_id == "MENTAL_HEALTH"


# ── Pathway Matching — Secondary Fields ───────────────────────────────────────


class TestPathwayMatchingSecondaryFields:
    def test_body_region_signal(self):
        """Pathway matched via body_region containing a trigger keyword phrase."""
        f = ExtractedFacts(
            chief_complaint="pain",
            body_region="chest pain",  # "chest pain" is a trigger keyword
        )
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_body_region_single_word_correctly_routes(self):
        """body_region='chest' alone correctly triggers CARDIAC via Pass 3 anchor matching.
        This was a known limitation of the old matcher that is now fixed.
        A patient who only says 'pain' but with body_region='chest' gets the CARDIAC pathway.
        """
        f = ExtractedFacts(
            chief_complaint="pain",
            body_region="chest",
        )
        # Pass 3: body_region anchor 'chest' -> CARDIAC
        assert match_pathway(f).pathway_id == "CARDIAC"

    def test_associated_symptoms_signal(self):
        """Pathway matched via associated_symptoms."""
        f = ExtractedFacts(
            chief_complaint="not feeling well",
            associated_symptoms=["shortness of breath", "chest tightness"],
        )
        # chest tightness triggers RESPIRATORY or associated signals lead to CARDIAC
        result = match_pathway(f)
        assert result.pathway_id in ("RESPIRATORY", "CARDIAC")

    def test_empty_complaint_returns_general(self):
        f = ExtractedFacts(chief_complaint="")
        assert match_pathway(f).pathway_id == "GENERAL"

    def test_none_complaint_returns_general(self):
        f = ExtractedFacts(chief_complaint=None)
        assert match_pathway(f).pathway_id == "GENERAL"


# ── Pathway Properties ─────────────────────────────────────────────────────────


class TestPathwayProperties:
    def test_cardiac_has_urgency_bias(self):
        from app.schemas.enums import Urgency
        assert CARDIAC_PATHWAY.urgency_bias == Urgency.URGENT

    def test_general_has_no_discriminators(self):
        assert len(GENERAL_PATHWAY.discriminators) == 0

    def test_general_has_no_trigger_keywords(self):
        assert len(GENERAL_PATHWAY.trigger_keywords) == 0

    def test_all_pathways_have_3_discriminators(self):
        """All concrete pathways (not GENERAL) should have exactly 3 discriminators."""
        from app.engine.clinical_pathways import ALL_PATHWAYS
        for pathway in ALL_PATHWAYS:
            assert len(pathway.discriminators) == 3, (
                f"Pathway {pathway.pathway_id} has {len(pathway.discriminators)} discriminators, expected 3"
            )

    def test_discriminator_fact_keys_are_unique_per_pathway(self):
        """Each pathway should have unique fact_keys for its discriminators."""
        from app.engine.clinical_pathways import ALL_PATHWAYS
        for pathway in ALL_PATHWAYS:
            keys = [d.fact_key for d in pathway.discriminators]
            assert len(keys) == len(set(keys)), (
                f"Pathway {pathway.pathway_id} has duplicate discriminator fact_keys"
            )


# ── Discriminator Completion ───────────────────────────────────────────────────


class TestDiscriminatorCompletion:
    def test_all_discriminators_unanswered_at_start(self):
        f = facts_with_complaint("chest pain")
        unanswered = get_unanswered_discriminators(CARDIAC_PATHWAY, f)
        assert len(unanswered) == 3
        assert unanswered[0].fact_key == "shortness_of_breath"

    def test_first_discriminator_answered_by_associated_symptom(self):
        """When 'shortness of breath' is in associated_symptoms, it's marked answered."""
        f = ExtractedFacts(
            chief_complaint="chest pain",
            associated_symptoms=["shortness of breath"],
        )
        unanswered = get_unanswered_discriminators(CARDIAC_PATHWAY, f)
        assert len(unanswered) == 2
        keys = [d.fact_key for d in unanswered]
        assert "shortness_of_breath" not in keys

    def test_second_discriminator_answered_preserves_first(self):
        """Answering the 2nd discriminator without the 1st keeps first unanswered."""
        f = ExtractedFacts(
            chief_complaint="chest pain",
            associated_symptoms=["radiating to arm"],
        )
        unanswered = get_unanswered_discriminators(CARDIAC_PATHWAY, f)
        # shortness_of_breath still unanswered (comes first)
        assert unanswered[0].fact_key == "shortness_of_breath"
        # radiating_pain is answered
        keys = [d.fact_key for d in unanswered]
        assert "radiating_pain" not in keys

    def test_all_discriminators_answered(self):
        f = ExtractedFacts(
            chief_complaint="chest pain",
            associated_symptoms=["shortness of breath", "radiating to jaw"],
            additional_context="came on suddenly",
        )
        unanswered = get_unanswered_discriminators(CARDIAC_PATHWAY, f)
        assert len(unanswered) == 0

    def test_pregnancy_discriminator_answered_by_top_level_field(self):
        """pregnancy_status discriminator is answered when is_pregnant is set."""
        f = ExtractedFacts(
            chief_complaint="pelvic pain",
            is_pregnant=False,
        )
        unanswered = get_unanswered_discriminators(GYNECOLOGICAL_PATHWAY, f)
        keys = [d.fact_key for d in unanswered]
        assert "pregnancy_status" not in keys

    def test_pregnancy_discriminator_unanswered_when_field_is_none(self):
        f = ExtractedFacts(chief_complaint="irregular periods")
        unanswered = get_unanswered_discriminators(GYNECOLOGICAL_PATHWAY, f)
        keys = [d.fact_key for d in unanswered]
        assert "pregnancy_status" in keys

    def test_general_pathway_always_returns_empty(self):
        """GENERAL_PATHWAY has no discriminators — always empty."""
        f = facts_with_complaint("feeling tired")
        unanswered = get_unanswered_discriminators(GENERAL_PATHWAY, f)
        assert unanswered == []

    def test_urdu_answer_signal_recognized(self):
        """Roman Urdu answer signals should mark discriminators as answered."""
        f = ExtractedFacts(
            chief_complaint="khansi",
            associated_symptoms=["bukhar bhi hai"],
        )
        unanswered = get_unanswered_discriminators(RESPIRATORY_PATHWAY, f)
        keys = [d.fact_key for d in unanswered]
        assert "fever_present" not in keys
