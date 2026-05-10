"""Velocity counters via shared fraud_aggregates (aligned with decision-api)."""

import pytest
from fraud_aggregates import AggregateStore, normalized_velocity_key_names

from .aggregate_fake_redis import FakeRedis

T0 = 1_700_000_000.0


@pytest.mark.asyncio
async def test_compute_features_matches_normalized_key_list():
    fake = FakeRedis()
    s = AggregateStore(redis_client=fake, clock=lambda: T0 + 200.0)
    await s.record_event(
        "t_vel",
        "e_vel",
        "ev1",
        {"amount": 10.0, "ip_address": "10.0.0.1", "device_id": "dev-1", "session_id": "sess-1"},
        ts=T0 + 1.0,
    )
    feats = await s.compute_features(
        "t_vel",
        "e_vel",
        {"amount": 1.0, "ip_address": "10.0.0.9", "device_id": "dev-z", "session_id": "sess-z"},
    )
    assert set(feats.keys()) == set(normalized_velocity_key_names())


def test_normalized_velocity_key_names_stable():
    names = normalized_velocity_key_names()
    assert "event_count_5m" in names
    assert "event_count_1h" in names
    assert "distinct_device_id_24h" in names
    assert "distinct_session_id_24h" in names
