"""Golden aggregate expectations with a fixed wall clock (CI gate for counter parity)."""

import pytest
from aggregate_fake_redis import FakeRedis
from decision_api.aggregates import AggregateStore

# Fixed epoch-like base so windows are deterministic relative to "now".
T0 = 1_700_000_000.0


@pytest.fixture
def golden_store():
    """AggregateStore + fake Redis; clock frozen 120s after first event window."""
    fake = FakeRedis()
    clock_at = T0 + 120.0
    s = AggregateStore(redis_client=fake, clock=lambda: clock_at)
    return s, fake


class TestGoldenEventCounts:
    @pytest.mark.asyncio
    async def test_seven_events_in_one_hour_window(self, golden_store):
        s, _ = golden_store
        for i in range(7):
            await s.record_event("golden_tenant", "golden_entity", f"ev-{i}", {}, ts=T0 + float(i))
        assert await s.count("golden_tenant", "golden_entity", 3600) == 7
        assert await s.count("golden_tenant", "golden_entity", 300) == 7

    @pytest.mark.asyncio
    async def test_events_outside_one_hour_excluded(self, golden_store):
        s, _ = golden_store
        await s.record_event("golden_tenant", "golden_entity", "old", {}, ts=T0 - 5000)
        await s.record_event("golden_tenant", "golden_entity", "new", {}, ts=T0 + 60)
        assert await s.count("golden_tenant", "golden_entity", 3600) == 1

    @pytest.mark.asyncio
    async def test_compute_features_golden_sum_and_distinct(self, golden_store):
        s, _ = golden_store
        await s.record_event(
            "golden_tenant",
            "golden_entity",
            "e1",
            {"amount": 10.0, "ip_address": "10.0.0.1", "session_id": "sess-a"},
            ts=T0 + 1,
        )
        await s.record_event(
            "golden_tenant",
            "golden_entity",
            "e2",
            {"amount": 25.5, "ip_address": "10.0.0.2", "session_id": "sess-b"},
            ts=T0 + 2,
        )
        feats = await s.compute_features(
            "golden_tenant",
            "golden_entity",
            {"amount": 1.0, "ip_address": "10.0.0.9", "session_id": "sess-z"},
        )
        assert feats["event_count_1h"] == 2
        assert feats["event_count_5m"] == 2
        assert abs(feats["sum_amount_1h"] - 35.5) < 1e-9
        assert abs(feats["avg_amount_1h"] - 17.75) < 1e-9
        assert feats["distinct_ip_address_24h"] == 2
        assert feats["distinct_session_id_24h"] == 2

    @pytest.mark.asyncio
    async def test_compute_features_distinct_sessions(self, golden_store):
        s, _ = golden_store
        await s.record_event(
            "golden_tenant",
            "golden_entity",
            "s1",
            {"session_id": "sess-a"},
            ts=T0 + 1,
        )
        await s.record_event(
            "golden_tenant",
            "golden_entity",
            "s2",
            {"session_id": "sess-b"},
            ts=T0 + 2,
        )
        feats = await s.compute_features(
            "golden_tenant",
            "golden_entity",
            {"session_id": "sess-z"},
        )
        assert feats["distinct_session_id_24h"] == 2


class TestGoldenEventCounts10xStress:
    """~10× default golden volume to catch ZSET / window drift (Epic C stretch)."""

    @pytest.mark.asyncio
    async def test_seventy_events_count_and_sum(self, golden_store):
        s, _ = golden_store
        for i in range(70):
            await s.record_event(
                "golden_tenant",
                "golden_entity",
                f"ev-stress-{i}",
                {
                    "amount": 1.0,
                    "ip_address": f"10.0.0.{i % 200}",
                    "device_id": f"d{i % 15}",
                    "session_id": f"s{i % 20}",
                },
                ts=T0 + float(i),
            )
        assert await s.count("golden_tenant", "golden_entity", 3600) == 70
        feats = await s.compute_features(
            "golden_tenant",
            "golden_entity",
            {"amount": 1.0, "ip_address": "10.0.0.9", "device_id": "dz", "session_id": "sz"},
        )
        assert feats["event_count_1h"] == 70
        assert abs(feats["sum_amount_1h"] - 70.0) < 1e-6
        assert feats["distinct_ip_address_24h"] >= 1
        assert feats["distinct_device_id_24h"] >= 1
        assert feats["distinct_session_id_24h"] >= 1
