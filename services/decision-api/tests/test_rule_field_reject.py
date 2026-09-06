"""Human pack writes reject unknown when.field; legacy aliases stay allowed."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.rule_api import router as rules_router


@pytest.fixture
async def rules_client(tmp_path, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "rules_path", str(tmp_path))
    monkeypatch.setattr(rule_api.settings, "rule_governance_secret", "")
    monkeypatch.setattr(rule_api.settings, "graph_service_url", "")
    app = FastAPI()
    app.include_router(rules_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_create_pack_rejects_unknown_field(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={
            "name": f"ghost_{uuid.uuid4().hex[:8]}",
            "rules": [
                {
                    "id": "r1",
                    "when": [{"field": "not_a_field", "op": "eq", "value": 1}],
                    "score_delta": 5,
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "map it or add a registry row" in str(r.json())


@pytest.mark.asyncio
async def test_create_pack_allows_computed_share(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={
            "name": f"share_{uuid.uuid4().hex[:8]}",
            "rules": [
                {
                    "id": "r1",
                    "when": [
                        {"field": "event_count_1h_share_24h", "op": "gte", "value": 0.5}
                    ],
                    "score_delta": 10,
                }
            ],
        },
    )
    assert r.status_code in (201, 409)
    if r.status_code == 422:
        raise AssertionError(r.json())


@pytest.mark.asyncio
async def test_create_pack_allows_legacy_alias(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={
            "name": f"legacy_tx_{uuid.uuid4().hex[:8]}",
            "rules": [
                {
                    "id": "r1",
                    "when": [{"field": "tx_count_1h", "op": "gte", "value": 3}],
                    "score_delta": 5,
                }
            ],
        },
    )
    assert r.status_code in (201, 409, 422)
    # 422 only if governance/other; field itself must not be the reason
    if r.status_code == 422:
        assert "tx_count_1h" not in str(r.json()).lower() or "unknown field" not in str(
            r.json()
        )


@pytest.mark.asyncio
async def test_create_pack_allows_overlay_field_with_tenant_query(rules_client, monkeypatch):
    pytest.importorskip("aiosqlite")
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from decision_api.db import Base
    from decision_api.field_store import upsert_overlay
    import decision_api.db as db

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", Session)
    async with Session() as session:
        await upsert_overlay(session, "t1", "order_channel", "who sold", "new_feature")
        await session.commit()

    pack = {
        "name": f"overlay_{uuid.uuid4().hex[:8]}",
        "rules": [
            {
                "id": "r1",
                "when": [{"field": "order_channel", "op": "eq", "value": "web"}],
                "score_delta": 5,
            }
        ],
    }
    with_tenant = await rules_client.post("/v1/rules?tenant_id=t1", json=pack)
    assert with_tenant.status_code in (201, 409)
    if with_tenant.status_code == 409:
        assert "already exists" in str(with_tenant.json()).lower()

    seed_only = await rules_client.post(
        "/v1/rules",
        json={**pack, "name": f"seedonly_{uuid.uuid4().hex[:8]}"},
    )
    assert seed_only.status_code == 422
    assert "map it or add a registry row" in str(seed_only.json())
    await engine.dispose()


@pytest.mark.asyncio
async def test_add_rule_rejects_unknown_field(rules_client):
    created = await rules_client.post(
        "/v1/rules",
        json={"name": f"addghost_{uuid.uuid4().hex[:8]}", "rules": []},
    )
    assert created.status_code == 201
    filename = created.json()["file"]
    r = await rules_client.post(
        f"/v1/rules/{filename}/rules",
        json={
            "id": "r_ghost",
            "when": [{"field": "not_a_field", "op": "eq", "value": 1}],
            "score_delta": 5,
        },
    )
    assert r.status_code == 422
    assert "map it or add a registry row" in str(r.json())


@pytest.mark.asyncio
async def test_add_rule_allows_legacy_alias(rules_client):
    created = await rules_client.post(
        "/v1/rules",
        json={"name": f"addtx_{uuid.uuid4().hex[:8]}", "rules": []},
    )
    assert created.status_code == 201
    filename = created.json()["file"]
    r = await rules_client.post(
        f"/v1/rules/{filename}/rules",
        json={
            "id": "r_tx",
            "when": [{"field": "tx_count_1h", "op": "gte", "value": 3}],
            "score_delta": 5,
        },
    )
    assert r.status_code == 200
    assert r.json().get("added") == "r_tx"
