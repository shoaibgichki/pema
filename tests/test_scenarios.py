"""
End-to-end PRD scenario tests (v2 — AI Conversation Engine).

All scenarios from PRD §12. Each test simulates the API with a mocked
conversation_engine.run_turn, so we can control what the AI "decides"
without real LLM calls.

Emergency scenarios (TS-02, TS-06, TS-12) need NO mocking — they are
handled by deterministic safety rules before the AI is ever called.

Tests validate:
- Correct specialty recommendation (returned by mocked AI)
- Correct urgency level
- Emergency escalation with correct rule IDs (deterministic)
- Session state transitions
- Audit trail completeness (FR-07.2)
"""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.engine.llm_client import LLMCallMetadata
from app.schemas.conversation import ConversationTurnOutput, TriageRecommendation
from app.schemas.enums import SessionStatus, Urgency
from app.schemas.fact import ExtractedFacts
from tests.conftest import create_test_session, send_test_message


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_llm_metadata() -> LLMCallMetadata:
    """Create a stub LLM metadata object."""
    return LLMCallMetadata(
        prompt_version="conversation_v1",
        model_name="test-model",
        latency_ms=50,
        trace_id="test-trace",
        raw_output={"test": True},
    )


def _ai_turn_with_facts(
    facts: ExtractedFacts,
    specialty: str,
    urgency: Urgency,
    *,
    message: str = "Based on what you've described, I recommend seeing a specialist.",
    reasoning: str = "Test clinical reasoning.",
    language: str = "en",
) -> ConversationTurnOutput:
    """Build a ConversationTurnOutput that immediately recommends."""
    return ConversationTurnOutput(
        message=message,
        extracted_facts=facts,
        recommendation=TriageRecommendation(
            specialty=specialty,
            urgency=urgency,
            confidence=0.9,
            rationale=reasoning,
        ),
        clinical_reasoning=reasoning,
        detected_language=language,
    )


def _ai_turn_gathering(
    facts: ExtractedFacts,
    question: str = "Can you tell me more?",
    language: str = "en",
) -> ConversationTurnOutput:
    """Build a ConversationTurnOutput that continues gathering info."""
    return ConversationTurnOutput(
        message=question,
        extracted_facts=facts,
        recommendation=None,
        clinical_reasoning="Still gathering information.",
        detected_language=language,
    )


def _patch_ai_engine(ai_output: ConversationTurnOutput):
    """
    Context manager that patches conversation_engine.run_turn to return
    the given output, and ensures the API key gate is satisfied.
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        mock = AsyncMock(return_value=(ai_output, _make_llm_metadata()))
        with patch("app.engine.orchestrator.run_turn", mock), \
             patch("app.engine.orchestrator.settings") as ms:
            ms.openai_api_key = "test-key"
            ms.openai_model = "test"
            ms.engine_version = "2.0.0"
            yield mock
    return _ctx()


# ── TS-01: Stomach pain, nausea, 32yo → Gastroenterologist, Routine ──────


class TestTS01StomachPain:
    """TS-01: Adult with stomach pain after meals, nausea → Gastroenterologist, Routine."""

    @pytest.mark.asyncio
    async def test_ts01_gastroenterologist_routine(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="stomach pain after meals",
            body_region="abdomen",
            age=32, sex="male",
            duration="3 days", severity="moderate",
            associated_symptoms=["nausea", "bloating"],
        )
        ai_output = _ai_turn_with_facts(
            facts, "gastroenterologist", Urgency.ROUTINE,
        )
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I've been having a bad stomach ache for 3 days")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "gastroenterologist"
            assert resp["urgency"] == "routine"


# ── TS-02: Chest pain + SOB → Emergency escalation (DETERMINISTIC) ────────


class TestTS02ChestPainEmergency:
    """TS-02: Adult with chest pain + SOB → Emergency escalation."""

    @pytest.mark.asyncio
    async def test_ts02_emergency_escalation(self, client: AsyncClient):
        # No mock needed — safety rules handle this deterministically
        session = await create_test_session(client)
        resp = await send_test_message(client, session["id"],
            "I have severe chest pain and I can't breathe properly")

        assert resp["session_status"] == "escalated"
        assert any(r["rule_id"] == "RF-001" for r in resp["triggered_rules"])
        assert "EMERGENCY" in resp["system_message"]
        assert "1122" in resp["system_message"]


# ── TS-03: Child age 3, fever >104°F → Emergency (DETERMINISTIC) ─────────


class TestTS03ChildHighFever:
    """TS-03: Child age 3 with high fever >104°F → Emergency escalation."""

    @pytest.mark.asyncio
    async def test_ts03_child_fever_emergency(self, client: AsyncClient):
        # Safety rules fire before AI — mock the normalization so child_under_5 check works
        facts = ExtractedFacts(chief_complaint="very high fever over 104 degrees", age=3)
        with patch("app.engine.orchestrator.normalize_for_safety",
                   new=AsyncMock(return_value=("very high fever over 104 degrees", None))), \
             patch("app.engine.orchestrator.session_manager.get_session_facts",
                   new=AsyncMock(return_value=facts)):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "My 3 year old son has a very high fever over 104 degrees fahrenheit")

        assert resp["session_status"] == "escalated"
        assert "EMERGENCY" in resp["system_message"]


# ── TS-04: Headaches, blurred vision → Neurologist, Urgent ───────────────


class TestTS04HeadacheVision:
    """TS-04: Adult with persistent headaches, blurred vision → Neurologist, Urgent."""

    @pytest.mark.asyncio
    async def test_ts04_neurologist_urgent(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="persistent headaches with blurred vision",
            body_region="head", age=40, sex="male",
            duration="2 weeks", severity="severe",
            associated_symptoms=["blurred vision", "dizziness"],
        )
        ai_output = _ai_turn_with_facts(facts, "neurologist", Urgency.URGENT)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I've been having severe headaches for 2 weeks with blurred vision")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "neurologist"
            assert resp["urgency"] == "urgent"


# ── TS-05: Irregular periods, pelvic pain → Gynecologist, Routine ─────────


class TestTS05IrregularPeriods:
    """TS-05: Adult female with irregular periods, pelvic pain → Gynecologist, Routine."""

    @pytest.mark.asyncio
    async def test_ts05_gynecologist_routine(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="irregular periods with pelvic pain",
            body_region="pelvic", age=28, sex="female",
            duration="5 days", severity="mild",
            associated_symptoms=["pelvic pain", "cramps", "irregular bleeding"],
            is_pregnant=False,
        )
        ai_output = _ai_turn_with_facts(facts, "gynecologist", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I have had irregular menstrual cycles and pelvic pain for a week")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "gynecologist"


# ── TS-06: Pregnant + bleeding → Emergency (DETERMINISTIC) ───────────────


class TestTS06PregnancyBleeding:
    """TS-06: Pregnant woman with bleeding → Emergency escalation."""

    @pytest.mark.asyncio
    async def test_ts06_pregnancy_emergency(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await send_test_message(client, session["id"],
            "I am pregnant and I am bleeding heavily, there is a lot of blood")
        assert resp["session_status"] == "escalated"
        assert any(r["rule_id"] == "RF-010" for r in resp["triggered_rules"])
        assert "EMERGENCY" in resp["system_message"]


# ── TS-07: Skin rash, 2 weeks → Dermatologist, Routine ───────────────────


class TestTS07SkinRash:
    """TS-07: Adult with skin rash for 2 weeks → Dermatologist, Routine."""

    @pytest.mark.asyncio
    async def test_ts07_dermatologist_routine(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="skin rash on arms and legs",
            body_region="skin", age=25, sex="male",
            duration="2 weeks", severity="mild",
            associated_symptoms=["itching"],
        )
        ai_output = _ai_turn_with_facts(facts, "dermatologist", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I have a rash on my arms and legs for 2 weeks with itching")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "dermatologist"


# ── TS-08: Ear pain, hearing loss → ENT, Routine ─────────────────────────


class TestTS08EarPain:
    """TS-08: Adult with ear pain, hearing loss → ENT, Routine."""

    @pytest.mark.asyncio
    async def test_ts08_ent_routine(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="ear pain and difficulty hearing",
            body_region="ear", age=45, sex="male",
            duration="1 week", severity="moderate",
            associated_symptoms=["hearing loss"],
        )
        ai_output = _ai_turn_with_facts(facts, "ent", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I have ear pain and trouble hearing for a week")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "ent"
            assert resp["urgency"] == "routine"


# ── TS-09: Cough, wheezing, 1 month → Pulmonologist, Urgent ──────────────


class TestTS09CoughWheezing:
    """TS-09: Adult with cough, wheezing for 1 month → Pulmonologist, Urgent."""

    @pytest.mark.asyncio
    async def test_ts09_pulmonologist_urgent(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="persistent cough with wheezing",
            body_region="chest", age=50, sex="male",
            duration="1 month", severity="moderate",
            associated_symptoms=["wheezing", "shortness of breath"],
        )
        ai_output = _ai_turn_with_facts(facts, "pulmonologist", Urgency.URGENT)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I've had a cough and wheezing for a month now")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "pulmonologist"
            assert resp["urgency"] == "urgent"


# ── TS-10: Joint pain, swelling → Orthopedist, Routine ───────────────────


class TestTS10JointPain:
    """TS-10: Adult with joint pain, swelling in knees → Orthopedist, Routine."""

    @pytest.mark.asyncio
    async def test_ts10_orthopedist_routine(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="joint pain and swelling in both knees",
            body_region="knees", age=55, sex="female",
            duration="3 weeks", severity="moderate",
            associated_symptoms=["swelling", "stiffness"],
        )
        ai_output = _ai_turn_with_facts(facts, "orthopedist", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "My knees are painful and swollen for 3 weeks")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "orthopedist"


# ── TS-11: Painful urination, blood → Urologist, Urgent ──────────────────


class TestTS11PainfulUrination:
    """TS-11: Adult with painful urination, blood in urine → Urologist, Urgent."""

    @pytest.mark.asyncio
    async def test_ts11_urologist_urgent(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="painful urination with blood in urine",
            body_region="urinary", age=35, sex="male",
            duration="5 days", severity="moderate",
            associated_symptoms=["blood in urine", "frequent urination"],
        )
        ai_output = _ai_turn_with_facts(facts, "urologist", Urgency.URGENT)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I have painful urination and blood in my urine for 5 days")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "urologist"
            assert resp["urgency"] == "urgent"


# ── TS-12: Suicidal thoughts → Emergency + crisis helpline (DETERMINISTIC) ─


class TestTS12SuicidalIdeation:
    """TS-12: User mentions suicidal thoughts → Emergency + crisis helpline info."""

    @pytest.mark.asyncio
    async def test_ts12_emergency_with_helpline(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await send_test_message(client, session["id"],
            "I want to end my life, I can't take it anymore")

        assert resp["session_status"] == "escalated"
        assert any(r["rule_id"] == "RF-004" for r in resp["triggered_rules"])
        assert "EMERGENCY" in resp["system_message"]
        msg = resp["system_message"]
        assert "Umang" in msg or "Taskeen" in msg or "0311" in msg or "0316" in msg


# ── TS-13: Roman Urdu input → Correct facts extracted, UR response ────────


class TestTS13RomanUrdu:
    """TS-13: Roman Urdu input → facts extracted, follow-ups in Roman Urdu."""

    @pytest.mark.asyncio
    async def test_ts13_roman_urdu_flow(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="bukhar aur sar dard",
            body_region="head", age=30, sex="male",
            duration="2 din", severity="moderate",
        )
        ai_output = _ai_turn_with_facts(
            facts, "neurologist", Urgency.ROUTINE,
            message="Aapki takleef samajh aa gayi. Aapko ek neurologist se milna chahiye.",
            language="ur",
        )
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client, language="ur")
            resp = await send_test_message(client, session["id"],
                "mujhe bukhar hai aur sar dard ho raha hai 2 din se")

            extracted = resp["extracted_facts"]
            assert extracted["chief_complaint"] is not None
            assert extracted["age"] == 30
            assert resp["session_status"] == "completed"


# ── TS-14: Mixed language → Correct extraction and specialty ──────────────


class TestTS14MixedLanguage:
    """TS-14: Mixed-language input → facts extracted, correct specialty."""

    @pytest.mark.asyncio
    async def test_ts14_mixed_language(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="back pain for 1 week",
            body_region="back", age=30, sex="male",
            duration="1 week", severity="moderate",
            associated_symptoms=["kamar dard"],
        )
        ai_output = _ai_turn_with_facts(facts, "orthopedist", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "meri back mein pain hai from 1 week")
            assert resp["session_status"] == "completed"
            assert resp["specialty"] == "orthopedist"


# ── TS-15: Minimal info, AI keeps gathering, eventually GP default ─────────


class TestTS15MinimalInfo:
    """TS-15: User provides minimal info → AI gathers more, GP default if still vague."""

    @pytest.mark.asyncio
    async def test_ts15_gp_default_when_vague(self, client: AsyncClient):
        """After multiple turns of vague info, AI recommends GP."""
        minimal_facts = ExtractedFacts(chief_complaint="feeling unwell")

        # First turn: AI is still gathering
        gathering_output = _ai_turn_gathering(
            minimal_facts,
            question="Can you tell me more about how you are feeling unwell?",
        )
        # Second turn: AI gives up and recommends GP
        gp_output = _ai_turn_with_facts(
            minimal_facts, "general_practitioner", Urgency.ROUTINE,
            message="A General Practitioner would be the best starting point for a general checkup.",
        )

        with _patch_ai_engine(gathering_output):
            session = await create_test_session(client)
            resp1 = await send_test_message(client, session["id"],
                "I don't know, just not feeling well")
            assert resp1["session_status"] == "fact_gathering"

        with _patch_ai_engine(gp_output):
            resp2 = await send_test_message(client, session["id"],
                "I really can't describe it better")
            assert resp2["session_status"] == "completed"
            assert resp2["specialty"] == "general_practitioner"


# ── Session lifecycle and audit trail tests ───────────────────────────────


class TestSessionAuditTrail:
    """Verify audit data completeness for completed sessions (FR-07.2)."""

    @pytest.mark.asyncio
    async def test_completed_session_has_audit_data(self, client: AsyncClient):
        facts = ExtractedFacts(
            chief_complaint="stomach pain with nausea",
            body_region="abdomen", age=30, sex="male",
            duration="3 days", severity="moderate",
            associated_symptoms=["nausea", "bloating"],
        )
        ai_output = _ai_turn_with_facts(
            facts, "gastroenterologist", Urgency.ROUTINE,
        )
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            await send_test_message(client, session["id"],
                "I have stomach pain with nausea and bloating")

        admin_resp = await client.get(f"/admin/sessions/{session['id']}")
        assert admin_resp.status_code == 200
        detail = admin_resp.json()

        assert detail["status"] == "completed"
        assert len(detail["messages"]) >= 3  # framing + user + system
        assert detail["extracted_facts"] is not None
        assert detail["specialty"] is not None
        assert detail["urgency"] is not None

    @pytest.mark.asyncio
    async def test_escalated_session_has_rule_events(self, client: AsyncClient):
        session = await create_test_session(client)
        await send_test_message(client, session["id"],
            "I have chest pain and shortness of breath")

        admin_resp = await client.get(f"/admin/sessions/{session['id']}")
        detail = admin_resp.json()

        assert detail["status"] == "escalated"
        assert len(detail["rule_events"]) > 0
        assert any("RF-001" in r["rule_name"] for r in detail["rule_events"])

    @pytest.mark.asyncio
    async def test_completed_session_rejects_new_messages(self, client: AsyncClient):
        """A completed session should not accept new messages (terminal state)."""
        facts = ExtractedFacts(
            chief_complaint="ear pain",
            body_region="ear", age=30, sex="male",
            duration="3 days", severity="mild",
            associated_symptoms=["hearing loss"],
        )
        ai_output = _ai_turn_with_facts(facts, "ent", Urgency.ROUTINE)
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client)
            resp = await send_test_message(client, session["id"],
                "I have ear pain and hearing loss")
            assert resp["session_status"] == "completed"

        fail_resp = await client.post(
            f"/sessions/{session['id']}/messages",
            json={"text": "hello again"},
        )
        assert fail_resp.status_code == 404

# ── Doctor Mode Specific Tests ──────────────────────────────────────────────

class TestDoctorMode:
    """Verify behavior specific to the Doctor Consultant Mode."""

    @pytest.mark.asyncio
    async def test_doctor_mode_bypasses_emergency(self, client: AsyncClient):
        """In Doctor mode, severe symptoms should NOT trigger the deterministic emergency template."""
        facts = ExtractedFacts(
            chief_complaint="chest pain and shortness of breath",
        )
        ai_output = _ai_turn_with_facts(
            facts, "emergency_department", Urgency.EMERGENCY,
            message="Differential includes acute myocardial infarction. Check troponins and ECG immediately."
        )
        with _patch_ai_engine(ai_output):
            session = await create_test_session(client, mode="doctor")
            
            # This input triggers RF-001 in Patient Mode
            resp = await send_test_message(client, session["id"],
                "I have severe chest pain and I can't breathe properly")
            
            # The session should be completed by the AI, not escalated by deterministic rules
            assert resp["session_status"] == "completed"
            
            # AI's clinical response should be present, not the "1122" alert
            assert "acute myocardial infarction" in resp["system_message"]
            assert "1122" not in resp["system_message"]
            
            # Rule matches should still be logged and returned
            assert any(r["rule_id"] == "RF-001" for r in resp["triggered_rules"])
