"""Epic C C-4: velocity/query returns same 5m/1h/24h as AggregateStore on shared fake Redis."""

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "services", "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "decision-api", "tests"))

from .aggregate_fake_redis import FakeRedis
from fastapi.testclient import TestClient
from fraud_aggregates import AggregateStore
from feature_service.main import app

T0 = 1_700_000_000.0


@pytest.mark.asyncio
async def test_velocity_query_matches_aggregate_store_day60_windows(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "")
    fake = FakeRedis()
    clock_at = T0 + 120.0
    store = AggregateStore(redis_client=fake, clock=lambda: clock_at)

    with TestClient(app) as client:
        client.app.state.velocity_store = store
        client.app.state.redis_client = fake
        for i in range(4):
            await store.record_event(
                "fs_tenant",
                "fs_entity",
                f"e{i}",
                {"amount": 5.0, "session_id": f"s{i}"},
                ts=T0 + float(i),
            )
        direct = await store.compute_features("fs_tenant", "fs_entity", {"session_id": "z"})
        r = client.post(
            "/v1/velocity/query",
            json={
                "tenant_id": "fs_tenant",
                "entity_id": "fs_entity",
                "payload": {"session_id": "z"},
            },
        )
        assert r.status_code == 200
        vel = r.json()["velocity_counters"]
        for key in ("event_count_5m", "event_count_1h", "event_count_24h"):
            assert vel[key] == direct[key], key
