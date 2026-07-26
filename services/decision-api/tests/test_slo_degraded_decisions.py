"""GET /v1/slo includes degraded_decisions snapshot."""

from decision_api.degraded_decision_metrics import record_degraded_decision_metrics


def test_custom_counters_matching_and_slo_shape():
    from observability import Metrics

    m = Metrics(service="decision-api")
    m.inc("tarka_degraded_decision_total", 2)
    m.inc("tarka_degraded_decision_load_shed_total", 1)
    m.inc("tarka_degraded_decision_missing_feature_total", 1)
    m.inc("other_metric_total", 9)
    matched = m.custom_counters_matching("tarka_degraded_decision_")
    assert matched["tarka_degraded_decision_total"] == 2
    assert "other_metric_total" not in matched


def test_record_degraded_feeds_prefix():
    seen: list[str] = []
    record_degraded_decision_metrics(
        ["load_shedding:active"],
        metrics_inc=lambda name, **_k: seen.append(name),
    )
    assert "tarka_degraded_decision_load_shed_total" in seen
