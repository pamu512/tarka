"""Tenant event_type overlay HTTP (bare FastAPI, no AuthMiddleware)."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.db import Base, get_session
from decision_api.event_type_api import router as event_type_router
from decision_api import event_type_api


@pytest.fixture
async def session_and_client():
    pytest.importorskip("aiosqlite")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:

        async def _override_session():
            yield session

        app = FastAPI()
        app.include_router(event_type_router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[event_type_api._require_analyst] = lambda: None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield session, c
        app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_requires_tenant_id(session_and_client):
    _session, client = session_and_client
    r = await client.get("/v1/event-types")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_includes_seed(session_and_client):
    _session, client = session_and_client
    r = await client.get("/v1/event-types", params={"tenant_id": "t1"})
    assert r.status_code == 200
    names = r.json()["names"]
    for seed in ("login", "payment", "signup", "device", "session", "custom"):
        assert seed in names
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_get_includes_env(session_and_client, monkeypatch):
    _session, client = session_and_client
    monkeypatch.setenv("TARKA_EVENT_TYPES", "payout")
    r = await client.get("/v1/event-types", params={"tenant_id": "t1"})
    assert r.status_code == 200
    assert "payout" in r.json()["names"]


@pytest.mark.asyncio
async def test_demo_put_403(session_and_client, monkeypatch):
    _session, client = session_and_client
    monkeypatch.setattr(event_type_api.settings, "tarka_desk_profile", "demo")
    r = await client.put(
        "/v1/event-types",
        json={"tenant_id": "t1", "name": "refund"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "event types persist on product Postgres"}


@pytest.mark.asyncio
async def test_put_seed_is_noop_200(session_and_client):
    _session, client = session_and_client
    r = await client.put(
        "/v1/event-types",
        json={"tenant_id": "t1", "name": "payment"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "payment"


@pytest.mark.asyncio
async def test_put_bad_shape_400(session_and_client):
    _session, client = session_and_client
    r = await client.put(
        "/v1/event-types",
        json={"tenant_id": "t1", "name": "Refund"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_refund_then_evaluate_allows(session_and_client):
    session, client = session_and_client
    r = await client.put(
        "/v1/event-types",
        json={"tenant_id": "t1", "name": "refund"},
    )
    assert r.status_code == 200
    listed = await client.get("/v1/event-types", params={"tenant_id": "t1"})
    assert "refund" in listed.json()["names"]
    from decision_api.event_type_gate import require_allowed_event_type

    assert await require_allowed_event_type(session, "t1", "refund") == "refund"
