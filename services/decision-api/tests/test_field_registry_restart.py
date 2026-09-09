"""G1.2 — product map PUT survives restart; demo stays fixture / PUT 403."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api import field_api
from decision_api.db import Base, get_session
from decision_api.field_api import router as field_router
from decision_api.models import FieldMap, FieldRegistryRow

_REPO = Path(__file__).resolve().parents[3]
_CLAIM_LOCK = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_ARCHITECTURE = _REPO / "ARCHITECTURE.md"
_ONBOARDING = _REPO / "docs" / "docs" / "guides" / "field-registry-onboarding.md"
_FLOWS = _REPO / "docs" / "docs" / "guides" / "feature-data-flows.md"
_POSTURE = _REPO / "docs" / "contracts" / "feature-store-posture-v1.md"
_SEED = (
    _REPO
    / "services"
    / "decision-api"
    / "src"
    / "decision_api"
    / "data"
    / "field_registry_v1.json"
)


async def _asgi_client(engine) -> AsyncIterator[AsyncClient]:
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(field_router)
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[field_api._require_analyst] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_product_map_put_survives_restart(tmp_path, monkeypatch):
    """File-backed SQL stands in for product Postgres: commit, new engine, map still there."""
    pytest.importorskip("aiosqlite")
    monkeypatch.setattr(field_api.settings, "tarka_desk_profile", "product")
    url = f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}"

    engine1 = create_async_engine(url, poolclass=NullPool)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async for client in _asgi_client(engine1):
        put = await client.put(
            "/v1/fields/maps",
            json={
                "tenant_id": "acme",
                "buyer_key": "txn_amt",
                "registry_name": "amount",
            },
        )
        assert put.status_code == 200, put.text
        assert put.json()["buyer_key"] == "txn_amt"
    await engine1.dispose()

    engine2 = create_async_engine(url, poolclass=NullPool)
    async for client in _asgi_client(engine2):
        listed = await client.get("/v1/fields/maps", params={"tenant_id": "acme"})
        assert listed.status_code == 200, listed.text
        assert any(
            row["buyer_key"] == "txn_amt" and row["registry_name"] == "amount"
            for row in listed.json()
        )
    await engine2.dispose()


@pytest.mark.asyncio
async def test_demo_put_403_seed_fixture_still_lists(tmp_path, monkeypatch):
    pytest.importorskip("aiosqlite")
    monkeypatch.setattr(field_api.settings, "tarka_desk_profile", "demo")
    url = f"sqlite+aiosqlite:///{tmp_path / 'demo_registry.db'}"
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async for client in _asgi_client(engine):
        refused = await client.put(
            "/v1/fields/maps",
            json={
                "tenant_id": "acme",
                "buyer_key": "txn_amt",
                "registry_name": "amount",
            },
        )
        assert refused.status_code == 403
        assert refused.json() == {"detail": "maps persist on product Postgres"}
        listed = await client.get("/v1/fields", params={"tenant_id": "acme"})
        assert listed.status_code == 200
        names = {row["name"] for row in listed.json()}
        assert "amount" in names
        maps = await client.get("/v1/fields/maps", params={"tenant_id": "acme"})
        assert maps.status_code == 200
        assert maps.json() == []
    await engine.dispose()


def test_registry_tables_are_postgres_sot_not_windows():
    assert FieldMap.__tablename__ == "field_maps"
    assert FieldRegistryRow.__tablename__ == "field_registry"
    raw = json.loads(_SEED.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    for row in raw:
        assert isinstance(row, dict)
        assert "window_seconds" not in row
        assert "window" not in row


def test_claim_lock_and_docs_product_registry_durable():
    lock = _CLAIM_LOCK.read_text(encoding="utf-8")
    assert "field_registry" in lock
    assert "field_maps" in lock
    assert "Postgres" in lock
    assert "PUT 403" in lock or "fixture" in lock
    assert "counter_manifest" in lock
    arch = _ARCHITECTURE.read_text(encoding="utf-8")
    assert "field_registry" in arch
    assert "field_maps" in arch
    assert "PUT 403" in arch or "fixture" in arch
    onboard = _ONBOARDING.read_text(encoding="utf-8")
    assert "file/fixture" in onboard or "fixture" in onboard
    assert "403" in onboard
    flows = _FLOWS.read_text(encoding="utf-8")
    assert "field_registry" in flows
    assert "field_maps" in flows
    posture = _POSTURE.read_text(encoding="utf-8")
    assert "Postgres" in posture
    assert "403" in posture or "fixture" in posture
