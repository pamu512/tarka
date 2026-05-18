"""xFraud #69: graph decision explanation payload."""

from decision_api.graph_decision_explanation import (
    SCHEMA_ID,
    build_graph_decision_explanation_v1,
)


def test_build_explanation_from_risk_factors():
    out = build_graph_decision_explanation_v1(
        trace_id="tr-1",
        tenant_id="t1",
        entity_id="pay-9",
        graph_risk={
            "risk_score": 55.0,
            "risk_factors": ["connected_flagged:2", "shared_devices:1"],
        },
        graph_trace={"step": "graph_risk", "status": "ok", "reason": None},
    )
    assert out is not None
    assert out["schema_id"] == SCHEMA_ID
    assert out["trace_id"] == "tr-1"
    assert len(out["factors"]) == 2
    assert len(out["why_links"]) == 2
    assert out["why_links"][0]["evidence"][0]["kind"] == "decision_trace"


def test_build_explanation_none_when_no_graph_signal():
    assert (
        build_graph_decision_explanation_v1(
            trace_id="tr-2",
            tenant_id="t1",
            entity_id="e1",
            graph_risk=None,
            graph_trace={"step": "graph_risk", "status": "skipped"},
        )
        is None
    )
