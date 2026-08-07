"""API tests: promo-abuse and seller-integrity backed by durable rows (Track B3)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from integration_ingress.db import Base, get_session
from integration_ingress.main import app
from integration_ingress.promo_abuse_store import upsert_redemption
from integration_ingress.seller_integrity_store import upsert_seller
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "promo_seller_durable.db"
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


def _internal_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("INGRESS_INTERNAL_TOKEN", "test-internal-token")
    from integration_ingress.config import settings

    monkeypatch.setattr(settings, "ingress_internal_token", "test-internal-token")
    return {"X-Internal-Token": "test-internal-token"}


@pytest.mark.asyncio
async def test_promo_empty_tenant_returns_empty_list(client: AsyncClient) -> None:
    r = await client.get(
        "/v1/analytics/promo-abuse",
        params={"tenant_id": "empty_promo", "coupon_code": "NEWUSER50"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "durable"
    assert body["users"] == []
    assert body["summary"]["unique_users"] == 0


@pytest.mark.asyncio
async def test_promo_record_then_list_returns_durable(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _internal_headers(monkeypatch)
    r = await client.post(
        "/v1/internal/marketplace/promo-redemptions",
        headers=headers,
        json={
            "tenant_id": "promo_t",
            "coupon_code": "SAVE20",
            "user_id": "user_real_1",
            "device_id": "dev_a",
            "order_total": 55.5,
            "trace_id": "tr_promo_1",
            "display_name": "Real User",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["user_id"] == "user_real_1"

    listed = await client.get(
        "/v1/analytics/promo-abuse",
        params={"tenant_id": "promo_t", "coupon_code": "SAVE20"},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["source"] == "durable"
    assert len(body["users"]) == 1
    assert body["users"][0]["user_id"] == "user_real_1"
    assert body["summary"]["unique_users"] == 1


@pytest.mark.asyncio
async def test_promo_internal_rejects_bad_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _internal_headers(monkeypatch)
    r = await client.post(
        "/v1/internal/marketplace/promo-redemptions",
        headers={"X-Internal-Token": "wrong"},
        json={
            "tenant_id": "t",
            "coupon_code": "X",
            "user_id": "u",
            "trace_id": "bad",
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_seller_empty_tenant_returns_empty_list(client: AsyncClient) -> None:
    r = await client.get(
        "/v1/marketplace/seller-integrity",
        params={"tenant_id": "empty_seller"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "durable"
    assert body["sellers"] == []
    assert body["summary"]["seller_count"] == 0


@pytest.mark.asyncio
async def test_seller_record_then_list_returns_durable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _internal_headers(monkeypatch)
    r = await client.post(
        "/v1/internal/marketplace/seller-integrity",
        headers=headers,
        json={
            "tenant_id": "seller_t",
            "seller_id": "seller_real_1",
            "successful_deliveries": 200,
            "review_count": 70,
            "display_name": "Real Seller",
            "store_slug": "real-store",
            "category": "electronics",
            "avg_rating": 4.5,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["seller_id"] == "seller_real_1"

    listed = await client.get(
        "/v1/marketplace/seller-integrity",
        params={"tenant_id": "seller_t"},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["source"] == "durable"
    assert len(body["sellers"]) == 1
    row = body["sellers"][0]
    assert row["seller_id"] == "seller_real_1"
    assert row["integrity_tier"] == "trusted"
    assert row["integrity_score"] >= 85


@pytest.mark.asyncio
async def test_store_upsert_idempotent_promo_trace(session: AsyncSession) -> None:
    row1, mat1 = await upsert_redemption(
        session,
        tenant_id="idem",
        coupon_code="CODE",
        user_id="u1",
        trace_id="same_trace",
        order_total=10.0,
    )
    row2, mat2 = await upsert_redemption(
        session,
        tenant_id="idem",
        coupon_code="CODE",
        user_id="u1",
        trace_id="same_trace",
        order_total=12.0,
    )
    assert mat1 is True
    assert mat2 is False
    assert row1["id"] == row2["id"]
    assert row2["order_total"] == 12.0


@pytest.mark.asyncio
async def test_store_seller_upsert_updates_existing(session: AsyncSession) -> None:
    row1, mat1 = await upsert_seller(
        session,
        tenant_id="idem_s",
        seller_id="s1",
        successful_deliveries=10,
        review_count=2,
    )
    row2, mat2 = await upsert_seller(
        session,
        tenant_id="idem_s",
        seller_id="s1",
        successful_deliveries=0,
        review_count=5,
    )
    assert mat1 is True
    assert mat2 is False
    assert row1["id"] == row2["id"]
    assert row2["review_count"] == 5
    assert row2["successful_deliveries"] == 0
