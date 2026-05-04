from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from aggregate_fake_redis import FakeRedis
from decision_api.aggregates import AggregateStore

"""Evaluate path + AggregateStore: counters must reach rule features (parity / TPS guard)."""


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


async def _session_override():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    yield mock_session


@pytest.fixture
async def aggregate_eval_client():
    """ASGI client with real AggregateStore + FakeRedis; captures features passed to rule engine."""
    fake = FakeRedis()
    store = AggregateStore(redis_client=fake)
    captured: list[tuple[dict, list]] = []

    def capture_rules(features: dict, tags: list, *args, **kwargs) -> tuple:
        captured.append((dict(features), list(tags)))
        return ([], [], 0.0, [])

    list_store = MagicMock()
    list_store.check = AsyncMock(return_value=SimpleNamespace(found=False))

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=["merged:tag"])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.check_consortium_signal = AsyncMock(return_value=None)
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store", store):
                    with patch("decision_api.main.evaluate_json_rules", side_effect=capture_rules):
                        with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                            with patch("decision_api.main._fetch_ml_score", new_callable=AsyncMock, return_value=(None, {})):
                                with patch("decision_api.main._fetch_graph_risk", new_callable=AsyncMock, return_value=None):
                                    with patch("decision_api.main._get_list_store", return_value=list_store):
                                        with patch("decision_api.main.fingerprint_store") as fp:
                                            fp._client = None
                                            from decision_api.main import app, get_session

                                            app.state.http = AsyncMock()
                                            app.dependency_overrides = {}
                                            app.dependency_overrides[get_session] = _session_override
                                            transport = httpx.ASGITransport(app=app)
                                            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                                                c._captured = captured
                                                c._mock_redis = mock_redis
                                                yield c
                                            app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_evaluate_second_request_sees_prior_aggregate_counts(aggregate_eval_client):
    """After one evaluate, the next for same tenant/entity must inject event_count_* from AggregateStore."""
    c = aggregate_eval_client
    body = {
        "tenant_id": "agg_gate_tenant",
        "event_type": "payment",
        "entity_id": "agg_gate_entity",
        "payload": {"amount": 50.0},
    }
    r1 = await c.post("/v1/decisions/evaluate", json=body)
    assert r1.status_code == 200
    r2 = await c.post("/v1/decisions/evaluate", json=body)
    assert r2.status_code == 200

    assert len(c._captured) >= 2
    feats_first, _ = c._captured[0]
    feats_second, _ = c._captured[1]

    assert feats_first.get("event_count_1h", 0) == 0, "first request should not see prior aggregates"
    assert int(feats_second.get("event_count_1h", 0)) >= 1, "second request must see recorded event"


@pytest.mark.asyncio
async def test_evaluate_calls_redis_merge_and_cache_score(aggregate_eval_client):
    c = aggregate_eval_client
    r = await c.post(
        "/v1/decisions/evaluate",
        json={"tenant_id": "t_redis", "event_type": "login", "entity_id": "e1", "payload": {}},
    )
    assert r.status_code == 200
    c._mock_redis.merge_tags.assert_awaited()
    c._mock_redis.set_cached_score.assert_awaited()
