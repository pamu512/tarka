"""Deep health endpoint (/v1/health/deep): Redis budget, ingest gate, optional ClickHouse."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
async def client():
    import decision_api.main  # noqa: F401 — ensure submodule exists for patch targets

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.close = AsyncMock()
    ping_mock = AsyncMock(return_value=True)
    mock_redis._client = MagicMock()
    mock_redis._client.ping = ping_mock
    mock_redis.get_tags = AsyncMock(return_value=[])
    mock_redis.merge_tags = AsyncMock(return_value=["sdk:vpn"])
    mock_redis.set_cached_score = AsyncMock()
    mock_redis.store_nonce = AsyncMock()
    mock_redis.consume_nonce = AsyncMock(return_value=True)
    mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)

    # Deep health imports redis_tags from redis_store; main holds a separate bound name.
    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.load_rules"):
            with patch("decision_api.main.agg_store") as mock_agg:
                mock_agg._client = None
                with (
                    patch("decision_api.redis_store.redis_tags", mock_redis),
                    patch("decision_api.main.redis_tags", mock_redis),
                    patch("decision_api.health_deep.redis_tags", mock_redis),
                ):
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.state.clickhouse_client = None
                    app.dependency_overrides = {}
                    import httpx

                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        c.tarka_app = app
                        c.redis_ping_mock = ping_mock
                        yield c
                    app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_health_deep_ok_when_budgets_pass(client, monkeypatch):
    from decision_api.config import settings as api_settings

    monkeypatch.setattr(api_settings, "health_deep_redis_max_ping_ms", 500.0)
    fake_stats = {
        "capacity": 256,
        "in_flight": 1,
        "buffer_pressure_percent": 80,
        "accepting_new_requests": True,
        "token_refill_per_sec": 500,
    }
    with patch(
        "decision_api.health_deep.tarka_ingest_stats",
        return_value=fake_stats,
    ):
        r = await client.get("/v1/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["checks"]["redis"]["status"] == "healthy"
    assert body["checks"]["clickhouse"]["status"] == "skipped"
    assert body["checks"]["rust_engine_ingest"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_deep_503_when_redis_ping_slow(client, monkeypatch):
    from decision_api.config import settings as api_settings

    monkeypatch.setattr(api_settings, "health_deep_redis_max_ping_ms", 5.0)

    async def slow_ping():
        await asyncio.sleep(0.012)
        return True

    client.redis_ping_mock.side_effect = slow_ping

    fake_stats = {
        "capacity": 256,
        "in_flight": 1,
        "buffer_pressure_percent": 80,
        "accepting_new_requests": True,
        "token_refill_per_sec": 500,
    }
    with patch(
        "decision_api.health_deep.tarka_ingest_stats",
        return_value=fake_stats,
    ):
        r = await client.get("/v1/health/deep")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["redis"]["status"] == "unhealthy"
    assert body["checks"]["redis"]["latency_ms"] > 5.0


@pytest.mark.asyncio
async def test_health_deep_alias_path_matches(client, monkeypatch):
    from decision_api.config import settings as api_settings

    monkeypatch.setattr(api_settings, "health_deep_redis_max_ping_ms", 500.0)
    fake_stats = {
        "capacity": 256,
        "in_flight": 1,
        "buffer_pressure_percent": 80,
        "accepting_new_requests": True,
        "token_refill_per_sec": 500,
    }
    with patch(
        "decision_api.health_deep.tarka_ingest_stats",
        return_value=fake_stats,
    ):
        r = await client.get("/health/deep")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_unified_ok(client, monkeypatch):
    from decision_api.config import settings as api_settings

    monkeypatch.setattr(api_settings, "json_rules_engine", "python")
    monkeypatch.setattr(api_settings, "health_deep_redis_max_ping_ms", 500.0)
    fake_stats = {
        "capacity": 256,
        "in_flight": 1,
        "buffer_pressure_percent": 80,
        "accepting_new_requests": True,
        "token_refill_per_sec": 500,
    }
    with patch(
        "decision_api.health_deep.tarka_ingest_stats",
        return_value=fake_stats,
    ):
        r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["probe"] == "unified"
    assert body["checks"]["postgres"]["status"] == "healthy"
    assert body["checks"]["redis"]["status"] == "healthy"
    assert body["checks"]["clickhouse"]["status"] == "skipped"
    assert body["checks"]["rust_engine"]["status"] == "healthy"
    assert body["checks"]["rust_engine"]["json_rules_engine"]["status"] == "skipped"
    assert body["checks"]["rust_engine"]["manifest_ingest"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_unified_503_when_postgres_fails(client, monkeypatch):
    from decision_api import health_deep
    from decision_api.config import settings as api_settings

    monkeypatch.setattr(api_settings, "json_rules_engine", "python")
    monkeypatch.setattr(api_settings, "health_deep_redis_max_ping_ms", 500.0)
    fake_stats = {
        "capacity": 256,
        "in_flight": 1,
        "buffer_pressure_percent": 80,
        "accepting_new_requests": True,
        "token_refill_per_sec": 500,
    }
    with (
        patch(
            "decision_api.health_deep.tarka_ingest_stats",
            return_value=fake_stats,
        ),
        patch.object(
            health_deep,
            "_check_postgres",
            new=AsyncMock(
                return_value=(
                    False,
                    {"status": "unhealthy", "reason": "simulated", "latency_ms": None},
                )
            ),
        ),
    ):
        r = await client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["postgres"]["status"] == "unhealthy"
