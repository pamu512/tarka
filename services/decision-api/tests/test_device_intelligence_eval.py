from __future__ import annotations

import pytest

from decision_api.device_intelligence import DeviceReputation
from decision_api.device_intelligence_eval import (
    apply_prior_device_reputation,
    device_ip_for_velocity,
    record_device_intelligence_outcome,
)


class _Store:
    def __init__(self, reputation=None, boom: bool = False, client=object()):
        self._client = client
        self.reputation = reputation
        self.boom = boom
        self.updated = None
        self.biometrics = None
        self.consortium = None
        self.ip_velocity = None

    async def get_device_reputation(self, tenant_id, device_id):
        if self.boom:
            raise RuntimeError("redis down")
        return self.reputation

    async def update_device_reputation(self, tenant_id, device_id, decision, is_fraud_confirmed=False):
        self.updated = (tenant_id, device_id, decision, is_fraud_confirmed)
        return self.reputation

    async def record_biometrics(self, tenant_id, entity_id, device_id, behavior):
        self.biometrics = behavior

    async def record_consortium_device(self, device_id, tenant_id, entity_id):
        self.consortium = (device_id, tenant_id, entity_id)
        return {}

    async def record_device_ip_velocity(self, device_id, ip, tenant_id):
        self.ip_velocity = (device_id, ip, tenant_id)
        return {}


def _rep() -> DeviceReputation:
    return DeviceReputation(
        device_id="dev-1",
        tenant_id="demo",
        total_evaluations=1,
        fraud_confirmed_count=0,
        review_count=0,
        deny_count=1,
        base_reputation=50.0,
        velocity_risk=50.0,
        cross_tenant_appearances=0,
        known_fraud_tenants=set(),
        first_seen=1.0,
        last_seen=2.0,
    )


@pytest.mark.asyncio
async def test_prior_row_sets_reputation_score_only():
    rep = _rep()
    features: dict = {}
    tags: list[str] = []
    await apply_prior_device_reputation(
        features, tags, store=_Store(reputation=rep), tenant_id="demo", device_id="dev-1", shadow=False
    )
    assert features == {"device_reputation_score": rep.calculate_risk_score()}
    assert tags == []


@pytest.mark.asyncio
async def test_missing_row_client_and_shadow_leave_features_unset():
    for store, shadow, device_id in (
        (_Store(reputation=None), False, "dev-1"),
        (_Store(client=None, reputation=_rep()), False, "dev-1"),
        (_Store(reputation=_rep()), True, "dev-1"),
        (_Store(reputation=_rep()), False, None),
        (_Store(reputation=_rep()), False, "  "),
    ):
        features: dict = {}
        tags: list[str] = []
        await apply_prior_device_reputation(
            features, tags, store=store, tenant_id="demo", device_id=device_id, shadow=shadow
        )
        assert features == {}
        assert tags == []


@pytest.mark.asyncio
async def test_read_error_tags_and_does_not_set_score():
    features: dict = {}
    tags: list[str] = []
    await apply_prior_device_reputation(
        features, tags, store=_Store(boom=True), tenant_id="demo", device_id="dev-1", shadow=False
    )
    assert features == {}
    assert tags == ["device_intelligence:unavailable"]


def test_device_ip_payload_wins():
    assert device_ip_for_velocity({"ip_address": " 203.0.113.8 "}, {"ip_address": "198.51.100.1"}) == "203.0.113.8"
    assert device_ip_for_velocity({}, {"ip_address": "198.51.100.1"}) == "198.51.100.1"
    assert device_ip_for_velocity(None, None) == ""


@pytest.mark.asyncio
async def test_record_outcome_is_not_a_fraud_label_and_skips_flat_signals():
    store = _Store()
    tags: list[str] = []
    await record_device_intelligence_outcome(
        tags,
        store=store,
        tenant_id="demo",
        entity_id="fraud_frank",
        device_id="dev-1",
        decision="deny",
        signals={"is_vpn": True, "is_emulator": True},
        ip="203.0.113.8",
        shadow=False,
    )
    assert store.updated == ("demo", "dev-1", "deny", False)
    assert store.biometrics is None
    assert store.consortium == ("dev-1", "demo", "fraud_frank")
    assert store.ip_velocity == ("dev-1", "203.0.113.8", "demo")
    assert tags == []


@pytest.mark.asyncio
async def test_record_biometrics_only_for_nested_groups_and_write_errors_tag():
    store = _Store()
    tags: list[str] = []
    await record_device_intelligence_outcome(
        tags,
        store=store,
        tenant_id="demo",
        entity_id="u1",
        device_id="dev-1",
        decision="allow",
        signals={"typing": {"avg_inter_key_ms": 80}},
        ip=None,
        shadow=False,
    )
    assert store.biometrics == {"typing": {"avg_inter_key_ms": 80}}
    assert store.ip_velocity is None

    class _Boom(_Store):
        async def update_device_reputation(self, *args, **kwargs):
            raise RuntimeError("redis down")

    tags2: list[str] = []
    await record_device_intelligence_outcome(
        tags2,
        store=_Boom(),
        tenant_id="demo",
        entity_id="u1",
        device_id="dev-1",
        decision="review",
        signals=None,
        ip=None,
        shadow=False,
    )
    assert tags2 == ["device_intelligence:unavailable"]


from pathlib import Path


def test_pipeline_and_lifespan_call_the_helper():
    root = Path(__file__).resolve().parents[1]
    pipeline = (root / "src/decision_api/evaluate/pipeline.py").read_text()
    main = (root / "src/decision_api/main.py").read_text()
    assert "apply_prior_device_reputation" in pipeline
    assert pipeline.count("record_device_intelligence_outcome") >= 3
    assert "device_intelligence.set_client(redis_tags._client)" in main
