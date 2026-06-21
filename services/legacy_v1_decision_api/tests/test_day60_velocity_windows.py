"""Day 60 / Epic C gate C-4: deterministic event_count_5m, 1h, 24h from shared AggregateStore."""

import pytest
from .aggregate_fake_redis import FakeRedis
from decision_api.aggregates import AggregateStore

T0 = 1_700_000_000.0


@pytest.fixture
def store():
    fake = FakeRedis()
    clock_at = T0 + 120.0
    return AggregateStore(redis_client=fake, clock=lambda: clock_at)


@pytest.mark.asyncio
async def test_day60_windows_5m_1h_24h_deterministic(store):
    """Feature-service reads the same Redis keys; these counts must match velocity/query."""
    for i in range(5):
        await store.record_event(
            "day60_tenant",
            "day60_entity",
            f"ev-{i}",
            {"amount": 10.0, "session_id": f"sess-{i}"},
            ts=T0 + float(i * 10),
        )
    # Event outside 24h window at clock T0+120
    await store.record_event(
        "day60_tenant",
        "day60_entity",
        "old",
        {"amount": 1.0},
        ts=T0 - 90_000,
    )
    feats = await store.compute_features(
        "day60_tenant",
        "day60_entity",
        {"session_id": "probe"},
    )
    assert feats["event_count_5m"] == 5
    assert feats["event_count_1h"] == 5
    assert feats["event_count_24h"] == 5
