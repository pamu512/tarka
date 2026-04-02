"""Unit tests for Pydantic schemas."""
import pytest
from pydantic import ValidationError

from decision_api.schemas import (
    DeviceContextIn,
    EvaluateRequest,
    EvaluateResponse,
    EventType,
)


class TestEvaluateRequest:
    def test_minimal_valid(self):
        r = EvaluateRequest(tenant_id="t1", event_type="login", entity_id="u1", payload={})
        assert r.tenant_id == "t1"
        assert r.event_type == EventType.login
        assert r.device_context is None

    def test_with_device_context(self):
        r = EvaluateRequest(
            tenant_id="t1",
            event_type="payment",
            entity_id="u1",
            payload={"amount": 100},
            device_context={"device_id": "abc", "platform": "web", "signals": {"is_vpn": True}},
        )
        assert r.device_context is not None
        assert r.device_context.device_id == "abc"
        assert r.device_context.signals["is_vpn"] is True

    def test_invalid_event_type(self):
        with pytest.raises(ValidationError):
            EvaluateRequest(tenant_id="t1", event_type="invalid_type", entity_id="u1", payload={})

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            EvaluateRequest(tenant_id="t1")

    def test_all_event_types(self):
        for et in ("login", "payment", "signup", "device", "session", "custom"):
            r = EvaluateRequest(tenant_id="t", event_type=et, entity_id="e", payload={})
            assert r.event_type.value == et


class TestEvaluateResponse:
    def test_minimal(self):
        r = EvaluateResponse(
            trace_id="00000000-0000-0000-0000-000000000001",
            decision="allow",
            score=15.0,
            tags=["test"],
            inference_context={
                "integrity_confidence": 0.9,
                "tamper_risk": 0.0,
                "network_trust": 1.0,
                "replay_risk": 0.0,
                "geo_consistency_risk": 0.0,
                "top_signals": [],
            },
        )
        assert r.decision == "allow"
        assert r.ml_score is None

    def test_full(self):
        r = EvaluateResponse(
            trace_id="00000000-0000-0000-0000-000000000001",
            decision="deny",
            score=92.0,
            tags=["sdk:bot", "high_amount"],
            rule_hits=["r1"],
            reasons=["rules:r1"],
            ml_score=88.0,
            inference_context={
                "integrity_confidence": 0.2,
                "tamper_risk": 0.7,
                "network_trust": 0.4,
                "replay_risk": 0.1,
                "geo_consistency_risk": 0.3,
                "top_signals": ["sdk:bot"],
            },
        )
        assert r.ml_score == 88.0
        assert len(r.tags) == 2
        assert r.inference_context.integrity_confidence == 0.2


class TestDeviceContextIn:
    def test_minimal(self):
        d = DeviceContextIn(device_id="abc")
        assert d.platform == "web"
        assert d.signals == {}
        assert d.attestation is None

    def test_with_signals(self):
        d = DeviceContextIn(device_id="abc", signals={"is_vpn": True, "canvas_fp_hash": "abc123"})
        assert d.signals["is_vpn"] is True
