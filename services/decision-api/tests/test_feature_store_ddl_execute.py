"""Admin feature-store raw DDL gate + ClickHouse execution wiring."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

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
                    from starlette.requests import Request

                    from decision_api.deps import get_clickhouse
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.dependency_overrides = {}
                    ch = MagicMock()

                    async def override_ch(request: Request):
                        return ch

                    app.dependency_overrides[get_clickhouse] = override_ch

                    import httpx

                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        c.tarka_ch = ch
                        yield c
                    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ddl_execute_rejects_multiple_statements(client):
    r = await client.post(
        "/v1/feature-store/ddl/execute",
        json={"sql": "CREATE TABLE a (x Int64); CREATE TABLE b (y Int64)"},
    )
    assert r.status_code == 400
    assert "Multiple statements" in r.json()["detail"]


@pytest.mark.asyncio
async def test_ddl_execute_rejects_disallowed_prefix(client):
    r = await client.post(
        "/v1/feature-store/ddl/execute",
        json={"sql": "SELECT 1"},
    )
    assert r.status_code == 400
    assert "must begin with" in r.json()["detail"]


@pytest.mark.asyncio
async def test_ddl_execute_propagates_clickhouse_error(client):
    ch = client.tarka_ch
    ch.command.side_effect = RuntimeError(
        "DB::Exception: Syntax error: failed at position 15"
    )

    with patch(
        "decision_api.feature_store_api.run_clickhouse_sync", new_callable=AsyncMock
    ) as rs:
        rs.side_effect = lambda _c, fn: fn()

        r = await client.post(
            "/v1/feature-store/ddl/execute",
            json={"sql": "CREATE TABLE tarka_ddl_test_x (id Int64) ENGINE = Memory"},
        )
    assert r.status_code == 422
    assert "Syntax error" in r.json()["detail"]


@pytest.mark.asyncio
async def test_ddl_execute_ok_when_clickhouse_succeeds(client):
    ch = client.tarka_ch
    with patch(
        "decision_api.feature_store_api.run_clickhouse_sync", new_callable=AsyncMock
    ) as rs:
        rs.side_effect = lambda _c, fn: fn()

        r = await client.post(
            "/v1/feature-store/ddl/execute",
            json={
                "sql": "CREATE TABLE IF NOT EXISTS tarka_ddl_test_y (id Int64) ENGINE = Memory"
            },
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "executed": True}
    ch.command.assert_called_once()
