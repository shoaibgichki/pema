"""
Test fixtures for PEMA test suite.

Uses SQLite async for testing (no PostgreSQL dependency in tests).
Provides test database, FastAPI test client, and helper factories.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.config import settings
from app.main import create_app
from app.schemas.enums import Language


# ── Isolate tests from real LLM keys ─────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _disable_llm_in_tests():
    """Ensure tests never hit real LLM APIs, even if .env has a key."""
    original_key = settings.openai_api_key
    settings.openai_api_key = ""
    yield
    settings.openai_api_key = original_key


# ── Test Database Setup ───────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_pema.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_maker = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean database session for each test."""
    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_maker() as session:
        yield session

    # Drop tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide a FastAPI test client with the test DB session."""
    app = create_app()

    async def override_get_db():
        try:
            yield db_session
        finally:
            db_session.expunge_all()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helper Factories ──────────────────────────────────────────────────────


async def create_test_session(
    client: AsyncClient,
    language: str = "en",
    mode: str = "patient",
) -> dict:
    """Create a session and return the response dict."""
    resp = await client.post("/sessions", json={"language": language, "mode": mode})
    assert resp.status_code == 201
    return resp.json()


async def send_test_message(
    client: AsyncClient,
    session_id: str,
    text: str,
) -> dict:
    """Send a message to a session and return the response dict."""
    resp = await client.post(
        f"/sessions/{session_id}/messages",
        json={"text": text},
    )
    assert resp.status_code == 200
    return resp.json()
