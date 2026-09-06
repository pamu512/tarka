"""Field registry HTTP surface (bare FastAPI, no AuthMiddleware)."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.db import Base, get_session
from decision_api.field_api import router as field_router
from decision_api import field_api


@pytest.fixture
async def client():
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
        app.include_router(field_router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[field_api._require_analyst] = lambda: None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
        app.dependency_overrides.clear()
    await engine.dispose()


def test_maps_and_discover_registered_before_name():
    paths = [
        r.path
        for r in field_router.routes
        if isinstance(r, APIRoute)
    ]
    assert paths.index("/v1/fields/maps") < paths.index("/v1/fields/{name}")
    assert paths.index("/v1/fields/discover") < paths.index("/v1/fields/{name}")


@pytest.mark.asyncio
async def test_maps_route_not_captured_as_name(client):
    r = await client.get("/v1/fields/maps", params={"tenant_id": "t1"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_put_tx_name_400(client):
    r = await client.put(
        "/v1/fields/tx_count_1h", json={"explanation": "no", "source": "new_feature"}
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_discover_order_channel_candidate_before_overlay(client):
    d = await client.post(
        "/v1/fields/discover",
        json={
            "tenant_id": "t1",
            "payload": {"txn_amt": 1, "order_channel": "web", "amount": 2},
        },
    )
    assert d.status_code == 200
    body = d.json()
    assert "amount" in body["already_named"]
    assert any(x["buyer_key"] == "order_channel" for x in body["candidates"])
    assert "order_channel" not in body["already_named"]


@pytest.mark.asyncio
async def test_put_and_discover_order_channel_already_named(client):
    r = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "who sold", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200
    await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "t1", "buyer_key": "txn_amt", "registry_name": "amount"},
    )
    d = await client.post(
        "/v1/fields/discover",
        json={
            "tenant_id": "t1",
            "payload": {"txn_amt": 1, "order_channel": "web", "amount": 2},
        },
    )
    body = d.json()
    assert "amount" in body["already_named"]
    assert "order_channel" in body["already_named"]
    assert any(x["buyer_key"] == "txn_amt" for x in body["mapped"])
    assert not any(x["buyer_key"] == "order_channel" for x in body["candidates"])


@pytest.mark.asyncio
async def test_demo_put_403(client, monkeypatch):
    monkeypatch.setattr(field_api.settings, "tarka_desk_profile", "demo")
    r = await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "t1", "buyer_key": "a", "registry_name": "amount"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "maps persist on product Postgres"}


@pytest.mark.asyncio
async def test_get_unknown_name_404(client):
    r = await client.get("/v1/fields/not_a_field", params={"tenant_id": "t1"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_seed_name_from_seed(client):
    r = await client.get("/v1/fields/amount", params={"tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "amount"
    assert body["source"] == "tarka_core"
    assert body["explanation"]


@pytest.mark.asyncio
async def test_get_name_strips_before_overlay(client):
    put = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "who sold", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert put.status_code == 200
    r = await client.get("/v1/fields/%20order_channel%20", params={"tenant_id": "t1"})
    assert r.status_code == 200
    assert r.json()["name"] == "order_channel"


@pytest.mark.asyncio
async def test_list_and_maps_missing_tenant_id_400(client):
    listed = await client.get("/v1/fields")
    assert listed.status_code == 400
    maps = await client.get("/v1/fields/maps")
    assert maps.status_code == 400


@pytest.mark.asyncio
async def test_put_seed_name_400(client):
    r = await client.put(
        "/v1/fields/amount",
        json={"explanation": "nope", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_overlay_tarka_core_source_rejected(client):
    r = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "who sold", "source": "tarka_core"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_put_empty_explanation_and_bad_source_422(client):
    empty = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert empty.status_code == 422
    bad = await client.put(
        "/v1/fields/order_channel",
        json={"explanation": "who sold", "source": "not_a_source"},
        params={"tenant_id": "t1"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_discover_non_dict_payload_422(client):
    r = await client.post(
        "/v1/fields/discover",
        json={"tenant_id": "t1", "payload": ["not", "a", "dict"]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_503_when_session_execute_raises():
    pytest.importorskip("aiosqlite")

    class _BoomSession:
        async def execute(self, *a, **k):
            raise RuntimeError("postgres down")

    async def _boom():
        yield _BoomSession()

    app = FastAPI()
    app.include_router(field_router)
    app.dependency_overrides[get_session] = _boom
    app.dependency_overrides[field_api._require_analyst] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/v1/fields", params={"tenant_id": "t1"})
    app.dependency_overrides.clear()
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_put_map_and_discover_strip_body_tenant_id(client):
    r = await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "  t1  ", "buyer_key": "txn_amt", "registry_name": "amount"},
    )
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "t1"
    listed = await client.get("/v1/fields/maps", params={"tenant_id": "t1"})
    assert listed.status_code == 200
    assert any(m["buyer_key"] == "txn_amt" for m in listed.json())
    blank = await client.put(
        "/v1/fields/maps",
        json={"tenant_id": "   ", "buyer_key": "x", "registry_name": "amount"},
    )
    assert blank.status_code == 400
    d = await client.post(
        "/v1/fields/discover",
        json={"tenant_id": "  t1  ", "payload": {"amount": 1}},
    )
    assert d.status_code == 200
    assert "amount" in d.json()["already_named"]


@pytest.mark.asyncio
async def test_put_legacy_distinct_alias_400(client):
    r = await client.put(
        "/v1/fields/distinct_devices_24h",
        json={"explanation": "nope", "source": "new_feature"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 400
