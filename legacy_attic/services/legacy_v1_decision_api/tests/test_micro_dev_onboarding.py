"""Micro-dev onboarding status + verify endpoints."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


@pytest.fixture
async def client():
    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=["sdk:vpn"])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.dependency_overrides = {}
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        c.tarka_app = app
                        yield c
                    app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_onboarding_status_shape(client):
    r = await client.get("/v1/micro-dev/onboarding/status")
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_state"] in ("uninitialized", "ready")
    assert body["engine"] in ("sqlite", "postgres")
    assert "analytics_store" in body
    assert isinstance(body["checks"], list)
    for c in body["checks"]:
        assert c["id"] in ("sqlite_permissions", "duckdb_bindings")
        assert c["verify_path"].startswith("/v1/micro-dev/onboarding/verify/")


@pytest.mark.asyncio
async def test_verify_sqlite_returns_200_under_test_sqlite(client):
    r = await client.get("/v1/micro-dev/onboarding/verify/sqlite")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("check") == "sqlite_permissions"


@pytest.mark.asyncio
async def test_verify_duckdb_returns_200_when_not_duck_store(client, monkeypatch):
    monkeypatch.setenv("TARKA_ANALYTICS_STORE", "clickhouse")
    r = await client.get("/v1/micro-dev/onboarding/verify/duckdb")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("check") == "duckdb_bindings"
