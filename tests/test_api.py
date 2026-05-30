"""
API integration tests (Phase 1).

Tests the REST API endpoints for session management and message processing.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import create_test_session, send_test_message


class TestHealthCheck:
    """Health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestCreateSession:
    """POST /sessions — create a new triage session."""

    @pytest.mark.asyncio
    async def test_create_session_default_language(self, client: AsyncClient):
        resp = await client.post("/sessions", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["status"] == "consent_framing"
        assert data["language"] == "en"
        assert data["framing_message"] is not None
        assert "PEMA" in data["framing_message"]

    @pytest.mark.asyncio
    async def test_create_session_urdu(self, client: AsyncClient):
        resp = await client.post("/sessions", json={"language": "ur"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["language"] == "ur"
        assert "PEMA" in data["framing_message"]
        assert "Assalam" in data["framing_message"]

    @pytest.mark.asyncio
    async def test_framing_message_contains_disclaimer(self, client: AsyncClient):
        data = await create_test_session(client)
        msg = data["framing_message"]
        assert "diagnose" in msg.lower() or "prescribe" in msg.lower()
        assert "1122" in msg


class TestSendMessage:
    """POST /sessions/{id}/messages — send user message."""

    @pytest.mark.asyncio
    async def test_send_message_basic(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await send_test_message(client, session["id"], "I have a headache")
        assert "system_message" in resp
        assert resp["session_status"] in ["fact_gathering", "chief_complaint"]
        assert resp["turn_number"] >= 1

    @pytest.mark.asyncio
    async def test_send_message_returns_facts(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await send_test_message(client, session["id"], "I have stomach pain")
        assert "extracted_facts" in resp

    @pytest.mark.asyncio
    async def test_emergency_triggers_escalation(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await send_test_message(
            client,
            session["id"],
            "I have chest pain and I can't breathe",
        )
        assert resp["session_status"] == "escalated"
        assert len(resp["triggered_rules"]) > 0
        assert "EMERGENCY" in resp["system_message"]

    @pytest.mark.asyncio
    async def test_escalated_session_rejects_messages(self, client: AsyncClient):
        session = await create_test_session(client)
        # Trigger emergency
        await send_test_message(
            client,
            session["id"],
            "I have chest pain and shortness of breath",
        )
        # Try to send another message
        resp = await client.post(
            f"/sessions/{session['id']}/messages",
            json={"text": "hello"},
        )
        assert resp.status_code == 404  # Terminal state

    @pytest.mark.asyncio
    async def test_invalid_session_returns_404(self, client: AsyncClient):
        resp = await client.post(
            "/sessions/00000000-0000-0000-0000-000000000000/messages",
            json={"text": "hello"},
        )
        assert resp.status_code == 404


class TestGetSession:
    """GET /sessions/{id} — get session state."""

    @pytest.mark.asyncio
    async def test_get_session(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await client.get(f"/sessions/{session['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == session["id"]
        assert data["status"] == "consent_framing"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, client: AsyncClient):
        resp = await client.get("/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestCloseSession:
    """POST /sessions/{id}/close — close or abandon a session."""

    @pytest.mark.asyncio
    async def test_close_session(self, client: AsyncClient):
        session = await create_test_session(client)
        resp = await client.post(
            f"/sessions/{session['id']}/close",
            json={"reason": "user requested"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "abandoned"

    @pytest.mark.asyncio
    async def test_close_already_closed_session(self, client: AsyncClient):
        session = await create_test_session(client)
        await client.post(f"/sessions/{session['id']}/close", json={})
        # Second close should succeed (idempotent)
        resp = await client.post(f"/sessions/{session['id']}/close", json={})
        assert resp.status_code == 200


class TestAdminEndpoints:
    """Admin API endpoints."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, client: AsyncClient):
        resp = await client.get("/admin/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_sessions_after_creation(self, client: AsyncClient):
        await create_test_session(client)
        await create_test_session(client, language="ur")
        resp = await client.get("/admin/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    @pytest.mark.asyncio
    async def test_get_session_detail(self, client: AsyncClient):
        session = await create_test_session(client)
        await send_test_message(client, session["id"], "I have a headache")
        resp = await client.get(f"/admin/sessions/{session['id']}")
        assert resp.status_code == 200
        detail = resp.json()
        assert len(detail["messages"]) >= 2  # framing + user + system reply
        assert detail["engine_version"] is not None

    @pytest.mark.asyncio
    async def test_get_session_detail_with_emergency(self, client: AsyncClient):
        session = await create_test_session(client)
        await send_test_message(
            client, session["id"], "I have chest pain and can't breathe"
        )
        resp = await client.get(f"/admin/sessions/{session['id']}")
        detail = resp.json()
        assert len(detail["rule_events"]) > 0
        assert detail["status"] == "escalated"

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client: AsyncClient):
        await create_test_session(client)
        resp = await client.get("/admin/sessions", params={"status": "consent_framing"})
        assert resp.status_code == 200
        for s in resp.json():
            assert s["status"] == "consent_framing"
