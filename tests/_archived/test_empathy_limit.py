
import pytest
from unittest.mock import patch
from httpx import AsyncClient

from app.schemas.fact import ExtractedFacts
from tests.conftest import create_test_session, send_test_message
from tests.test_scenarios import _mock_extract_returning, _stub_follow_up, _stub_recommendation

@pytest.mark.asyncio
async def test_empathy_rate_limiting_logic(client: AsyncClient):
    """
    Test that allow_sympathy is correctly calculated and passed:
    1. First turn (not expressed) -> True
    2. Second turn (already expressed, mild) -> False
    3. Third turn (already expressed, but severe) -> True
    """
    session = await create_test_session(client)
    session_id = session["id"]

    # Turn 1: No sympathy expressed yet
    facts_t1 = ExtractedFacts(chief_complaint="mild headache", severity="mild")
    with patch("app.engine.orchestrator.extract_facts", side_effect=_mock_extract_returning(facts_t1)), \
         patch("app.engine.orchestrator.compose_follow_up", side_effect=_stub_follow_up()) as mock_follow, \
         patch("app.engine.orchestrator.settings") as mock_settings:
        
        mock_settings.openai_api_key = "test-key"
        await send_test_message(client, session_id, "I have a headache")
        
        # Check that allow_sympathy was True
        _, kwargs = mock_follow.call_args
        assert kwargs["allow_sympathy"] is True

    # Turn 2: Sympathy was expressed, symptom is still mild
    facts_t2 = ExtractedFacts(severity="mild")
    with patch("app.engine.orchestrator.extract_facts", side_effect=_mock_extract_returning(facts_t2)), \
         patch("app.engine.orchestrator.compose_follow_up", side_effect=_stub_follow_up()) as mock_follow, \
         patch("app.engine.orchestrator.settings") as mock_settings:
        
        mock_settings.openai_api_key = "test-key"
        await send_test_message(client, session_id, "It's just a little bit of pain")
        
        # Check that allow_sympathy was False
        _, kwargs = mock_follow.call_args
        assert kwargs["allow_sympathy"] is False

    # Turn 3: Sympathy was expressed, but symptom is now severe
    facts_t3 = ExtractedFacts(severity="severe")
    with patch("app.engine.orchestrator.extract_facts", side_effect=_mock_extract_returning(facts_t3)), \
         patch("app.engine.orchestrator.compose_follow_up", side_effect=_stub_follow_up()) as mock_follow, \
         patch("app.engine.orchestrator.settings") as mock_settings:
        
        mock_settings.openai_api_key = "test-key"
        await send_test_message(client, session_id, "Wait, now it is severely painful")
        
        # Check that allow_sympathy was True again
        _, kwargs = mock_follow.call_args
        assert kwargs["allow_sympathy"] is True
