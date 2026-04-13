"""Internal counter manifest + replay API."""

import os
from unittest.mock import patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
async def client():
    from unittest.mock import AsyncMock, MagicMock

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=[])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.state.nats_js = None
                    app.state.nats_nc = None
                    app.dependency_overrides = {}
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                        yield c
                    app.dependency_overrides = {}


class TestInternalCountersManifest:
    @pytest.mark.asyncio
    async def test_get_manifest(self, client):
        r = await client.get("/v1/internal/counters/manifest")
        assert r.status_code == 200
        data = r.json()
        assert "manifest_version" in data
        assert "feature_outputs" in data


class TestInternalCountersReplay:
    @pytest.mark.asyncio
    async def test_replay_disabled_without_token(self, client, monkeypatch):
        monkeypatch.setenv("COUNTER_REPLAY_TOKEN", "")
        from decision_api.config import settings

        settings.counter_replay_token = ""

        r = await client.post(
            "/v1/internal/counters/replay",
            json={"scratch_redis_url": "redis://localhost:6379/15", "events": []},
        )
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_replay_rejects_bad_token(self, client, monkeypatch):
        monkeypatch.setenv("COUNTER_REPLAY_TOKEN", "good")
        from decision_api.config import settings

        settings.counter_replay_token = "good"

        r = await client.post(
            "/v1/internal/counters/replay",
            json={"scratch_redis_url": "redis://localhost:6379/15", "events": []},
            headers={"X-Tarka-Counter-Replay-Token": "wrong"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_replay_with_fake_redis(self, client, monkeypatch):
        from aggregate_fake_redis import FakeRedis

        monkeypatch.setenv("COUNTER_REPLAY_TOKEN", "tok")
        from decision_api.config import settings

        settings.counter_replay_token = "tok"

        fake = FakeRedis()

        def _from_url(url: str, **kwargs):
            return fake

        with patch("decision_api.internal_counters_api.aioredis.from_url", new=_from_url):
            r = await client.post(
                "/v1/internal/counters/replay",
                json={
                    "scratch_redis_url": "redis://localhost:6379/15",
                    "events": [
                        {
                            "tenant_id": "t1",
                            "entity_id": "e1",
                            "event_id": "x1",
                            "fields": {},
                            "ts": 1_700_000_100.0,
                        }
                    ],
                },
                headers={"X-Tarka-Counter-Replay-Token": "tok"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["recorded"] == 1
        assert "manifest_version" in body
