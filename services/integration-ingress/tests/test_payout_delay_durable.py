"""API tests: payout-delay list/release backed by durable holds (Marketplace P0 Task 3)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from integration_ingress.db import Base, get_session
from integration_ingress.main import app
from integration_ingress.payout_hold_store import release_hold, upsert_hold
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "payout_delay_durable.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
    headers = {"X-API-Key": key}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_list_returns_durable_hold_not_demo_only(client: AsyncClient, session: AsyncSession) -> None:
    await upsert_hold(
        session,
        tenant_id="demo",
        payout_id="po_real",
        entity_id="e1",
        status="held",
        hold_reason="tag:action:payout_hold",
        held_by="evaluate",
        decision_id="d",
        trace_id="t",
        tags=["action:payout_hold"],
        amount=10,
        currency="USD",
        hold_duration_hours=24,
    )
    r = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in ("durable", "durable+automation")
    assert any(p["payout_id"] == "po_real" for p in body["payouts"])


@pytest.mark.asyncio
async def test_release_updates_durable_row(client: AsyncClient, session: AsyncSession) -> None:
    await upsert_hold(
        session,
        tenant_id="demo",
        payout_id="po_rel",
        entity_id="e2",
        status="held",
        hold_reason="tag:action:payout_hold",
        held_by="evaluate",
        amount=50,
        currency="USD",
    )
    r = await client.post(
        "/v1/marketplace/payout-delay/po_rel/release",
        params={"tenant_id": "demo"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["release"]["status"] == "released"
    row = next(p for p in body["board"]["payouts"] if p["payout_id"] == "po_rel")
    assert row["status"] == "released"


@pytest.mark.asyncio
async def test_internal_create_payout_hold(client: AsyncClient, session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setenv("INGRESS_INTERNAL_TOKEN", "test-internal-token")
    from integration_ingress.config import settings

    monkeypatch.setattr(settings, "ingress_internal_token", "test-internal-token")

    r = await client.post(
        "/v1/internal/marketplace/payout-holds",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "tenant_id": "demo",
            "payout_id": "po_internal",
            "entity_id": "e3",
            "status": "held",
            "hold_reason": "tag:action:payout_hold",
            "held_by": "evaluate",
            "amount": 99,
            "currency": "USD",
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["payout_id"] == "po_internal"
    listed = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "demo"})
    assert any(p["payout_id"] == "po_internal" for p in listed.json()["payouts"])


@pytest.mark.asyncio
async def test_mule_automation_writes_durable_holds(client: AsyncClient, session: AsyncSession) -> None:
    """High mule_score candidates upsert held rows; list is not demo_aggregate."""
    await client.patch(
        "/v1/marketplace/payout-delay/config",
        json={
            "tenant_id": "mule_t",
            "automation_enabled": True,
            "mule_score_hold_threshold": 50,
        },
    )
    r = await client.get("/v1/marketplace/payout-delay", params={"tenant_id": "mule_t", "limit": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in ("durable", "durable+automation")
    held = [p for p in body["payouts"] if p["status"] == "held"]
    assert held, "expected mule automation to persist at least one held row"
    assert held[0]["held_by"] == "payout_delay_automation"
