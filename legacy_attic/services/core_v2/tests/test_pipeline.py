"""Integration tests for /v1/decide using async SQLite (no mocked database)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://unused:unused@127.0.0.1:65432/unused_placeholder",
)

import db

# Depth tuned so Pydantic accepts the payload while serde_json exceeds parse recursion.
RUST_SERDE_JSON_PARSE_BREAK_DEPTH = 180


def _nested_wrap_metadata(depth: int) -> dict:
    inner: dict[str, object] = {"leaf": True}
    for _ in range(depth):
        inner = {"wrap": inner}
    return inner


@pytest_asyncio.fixture
async def pipeline_client(monkeypatch: pytest.MonkeyPatch):
    """SQLite in-memory engine + dependency override; production Postgres engine unused."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(db, "AsyncSessionLocal", session_factory)

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_decide_returns_200_and_persists_audit_row(pipeline_client):
    client, session_factory = pipeline_client

    entity = uuid.uuid4()
    payload = {
        "entity_id": str(entity),
        "amount": 5000.01,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"channel": "pytest"},
    }

    response = await client.post("/v1/decide", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "decision" in body
    decision = body["decision"]
    assert decision in {"APPROVE", "FLAG_REVIEW"}

    async with session_factory() as verify_session:
        result = await verify_session.execute(select(db.AuditLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.entity_id == entity
    assert row.decision == decision
    assert row.raw_payload["amount"] == pytest.approx(payload["amount"])
    assert row.raw_payload["entity_id"] == payload["entity_id"]


async def _audit_log_row_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(select(db.AuditLog))
        return len(result.scalars().all())


def _assert_pydantic_v2_validation_error_payload(body: dict) -> None:
    """FastAPI wraps Pydantic V2 `ValidationError` as `{detail: [...]}`."""
    assert "detail" in body
    detail = body["detail"]
    assert isinstance(detail, list)
    assert len(detail) >= 1
    for item in detail:
        assert isinstance(item, dict)
        assert "type" in item
        assert "loc" in item
        assert "msg" in item
        assert isinstance(item["loc"], list)


@pytest.mark.asyncio
async def test_hostile_missing_amount_returns_422_and_no_db_writes(pipeline_client):
    client, session_factory = pipeline_client

    assert await _audit_log_row_count(session_factory) == 0

    entity = uuid.uuid4()
    payload = {
        "entity_id": str(entity),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"channel": "pytest-hostile"},
    }

    response = await client.post("/v1/decide", json=payload)

    assert response.status_code == 422
    body = response.json()
    _assert_pydantic_v2_validation_error_payload(body)
    assert any(
        "amount" in entry.get("loc", [])
        for entry in body["detail"]
        if isinstance(entry, dict)
    )

    assert await _audit_log_row_count(session_factory) == 0


@pytest.mark.asyncio
async def test_hostile_amount_string_returns_422_and_no_db_writes(pipeline_client):
    client, session_factory = pipeline_client

    assert await _audit_log_row_count(session_factory) == 0

    entity = uuid.uuid4()
    payload = {
        "entity_id": str(entity),
        "amount": "not-a-number",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"channel": "pytest-hostile"},
    }

    response = await client.post("/v1/decide", json=payload)

    assert response.status_code == 422
    body = response.json()
    _assert_pydantic_v2_validation_error_payload(body)
    assert any(
        "amount" in entry.get("loc", [])
        for entry in body["detail"]
        if isinstance(entry, dict)
    )

    assert await _audit_log_row_count(session_factory) == 0


@pytest.mark.asyncio
async def test_hostile_deep_metadata_rust_serde_fails_returns_400_empty_db(pipeline_client):
    """Deep nested metadata: passes FastAPI/Pydantic, fails Rust serde_json parse; must be 400 not 500."""
    client, session_factory = pipeline_client

    assert await _audit_log_row_count(session_factory) == 0

    entity = uuid.uuid4()
    payload = {
        "entity_id": str(entity),
        "amount": 100.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": _nested_wrap_metadata(RUST_SERDE_JSON_PARSE_BREAK_DEPTH),
    }

    response = await client.post("/v1/decide", json=payload)

    assert response.status_code == 400
    assert response.status_code != 500
    detail = response.json().get("detail", "")
    assert isinstance(detail, str)
    assert detail == "rule evaluation failed"

    assert await _audit_log_row_count(session_factory) == 0
