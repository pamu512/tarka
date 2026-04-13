"""Counter manifest parity with AggregateStore.compute_features."""

import pytest
from aggregate_fake_redis import FakeRedis
from decision_api.aggregates import AggregateStore
from decision_api.counter_manifest import expected_feature_names, load_counter_manifest_v1, manifest_version

T0 = 1_700_000_000.0


class TestCounterManifest:
    def test_load_manifest(self):
        m = load_counter_manifest_v1()
        assert m["manifest_version"]
        assert len(m["feature_outputs"]) >= 8

    def test_manifest_version_helper(self):
        assert manifest_version() == load_counter_manifest_v1()["manifest_version"]

    @pytest.mark.asyncio
    async def test_compute_features_keys_match_manifest_when_all_branches(self):
        """With amount + ip + device on the evaluate fields, outputs should match manifest exactly."""
        fake = FakeRedis()
        clock_at = T0 + 120.0
        s = AggregateStore(redis_client=fake, clock=lambda: clock_at)
        await s.record_event(
            "t_manifest",
            "e_manifest",
            "ev1",
            {"amount": 10.0, "ip_address": "10.0.0.1", "device_id": "dev-a"},
            ts=T0 + 1.0,
        )
        feats = await s.compute_features(
            "t_manifest",
            "e_manifest",
            {"amount": 1.0, "ip_address": "10.0.0.9", "device_id": "dev-z"},
        )
        assert set(feats.keys()) == expected_feature_names()
