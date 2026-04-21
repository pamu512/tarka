from decision_api.redis_store import _consortium_metrics_recompute


def test_consortium_metrics_recompute_normalizes_feedback_quality():
    state = {
        "tenants": ["tenant-a", "tenant-b"],
        "tenant_trust": {"tenant-a": 1.5, "tenant-b": 0.8},
        "signal_counts": {"device": 3, "ip": 2},
        "report_count": 5,
        "max_severity": 4.2,
        "weighted_report_score": 6.3,
        "false_positive_count": 2,
        "confirmed_fraud_count": 6,
    }
    out = _consortium_metrics_recompute(state)
    assert out["tenant_count"] == 2
    assert out["report_count"] == 5
    assert out["quality_score"] <= 1.5
    assert 0.0 <= out["false_positive_rate"] <= 1.0
    assert "tenant_trust" in out
