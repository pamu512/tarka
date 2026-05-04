"""Tenant kill-switch flags (R2.3) and fallback_reason helper (R2.4)."""

from decision_api.main import _compute_fallback_reason, _shape_inference_context_for_tier
from decision_api.tenant_flags import tenant_flag_enabled


def test_tenant_flag_enabled():
    assert tenant_flag_enabled({"disable_ml": True}, "disable_ml") is True
    assert tenant_flag_enabled({"disable_ml": "true"}, "disable_ml") is True
    assert tenant_flag_enabled({}, "disable_ml") is False


def test_compute_fallback_reason_from_tags():
    r = _compute_fallback_reason(["ml:unavailable", "opa:unavailable"], [])
    assert r
    assert "circuit_ml" in r
    assert "circuit_opa" in r


def test_compute_fallback_reason_covers_async_osint_and_counter_fallback():
    r = _compute_fallback_reason(["async_osint:unavailable", "counter:fallback_local_agg"], [])
    assert r
    assert "async_osint_redis" in r
    assert "counter_local_aggregate_fallback" in r


def test_compute_fallback_reason_rules_only(monkeypatch):
    from decision_api.config import settings

    monkeypatch.setattr(settings, "score_blend_strategy", "rules_only")
    r = _compute_fallback_reason([], [])
    assert r == "rules_only_blend"


def test_shape_inference_context_minimal_redacts_high_signal_details():
    source = {
        "driver_reasons": ["rule:velocity_guard"],
        "driver_explain": [{"reason": "rule:velocity_guard", "category": "rules", "label": "Rule hit: velocity_guard"}],
        "top_signals": ["sdk:vpn", "rule:velocity_guard"],
        "graph_risk_reasons": ["connected_flagged_3"],
        "ml_top_factors": [{"code": "HIGH_AMOUNT", "contribution": 0.2}],
        "ml_summary": "High amount + bad network",
        "policy_experiment_id": "exp-123",
    }
    out = _shape_inference_context_for_tier(source, "minimal")
    assert out["graph_risk_reasons"] == []
    assert out["ml_top_factors"] == []
    assert out["ml_summary"] is None
    assert out["policy_experiment_id"] is None
    assert out["top_signals"] == ["sdk", "rule"]
    assert out["driver_explain"][0]["label"] == ""
