"""Smoke: evaluate enrichment runtime bind + fallback shape."""

from decision_api.evaluate import enrichment
from decision_api.schemas import EvaluateRequest, EventType


def test_bind_runtime_and_feature_fallback() -> None:
    enrichment.bind_runtime(
        circuit_graph=object(),
        circuit_feature=object(),
        metrics_inc=lambda *_a, **_k: None,
        upstream_headers=lambda: {},
    )
    body = EvaluateRequest(
        tenant_id="t1",
        entity_id="e1",
        event_type=EventType.payment,
        payload={"amount": 1.0},
    )
    snap = enrichment.feature_snapshot_fallback(body, ["tag:a"])
    assert snap["tenant_id"] == "t1"
    assert snap["features"]["amount"] == 1.0
    assert snap["redis_tags"] == ["tag:a"]
