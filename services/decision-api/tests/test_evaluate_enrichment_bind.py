"""Smoke: evaluate enrichment runtime bind + fallback shape."""

import pytest

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


@pytest.mark.asyncio
async def test_empty_graph_url_tags_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrichment.bind_runtime(
        circuit_graph=object(),
        circuit_feature=object(),
        metrics_inc=lambda *_a, **_k: None,
        upstream_headers=lambda: {},
    )
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "")
    tags: list[str] = []
    data = await enrichment.fetch_graph_risk_wrapped(
        http=object(),  # type: ignore[arg-type]
        tenant_id="t1",
        entity_id="e1",
        degrade_tags=tags,
        tenant_flags={},
    )
    assert data is None
    assert "graph:unconfigured" in tags
    assert "graph:unavailable" not in tags


@pytest.mark.asyncio
async def test_empty_feature_url_tags_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrichment.bind_runtime(
        circuit_graph=object(),
        circuit_feature=object(),
        metrics_inc=lambda *_a, **_k: None,
        upstream_headers=lambda: {},
    )
    monkeypatch.setattr(enrichment.settings, "feature_service_url", "")
    body = EvaluateRequest(
        tenant_id="t1",
        entity_id="e1",
        event_type=EventType.payment,
        payload={"amount": 1.0},
    )
    tags: list[str] = []
    snap = await enrichment.fetch_feature_snapshot_wrapped(
        http=object(),  # type: ignore[arg-type]
        body=body,
        redis_tag_list=[],
        degrade_tags=tags,
        tenant_flags={},
    )
    assert snap["features"]["amount"] == 1.0
    assert "enrichment:unconfigured" in tags
    assert "enrichment:unavailable" not in tags


def test_parse_ml_disabled_and_missing_are_unscored_zero_is_real() -> None:
    from unittest.mock import patch

    from decision_api.evaluate.score import blend_scores, parse_ml_score_payload

    score, extra = parse_ml_score_payload({"score": 0.0, "model_version": "disabled"})
    assert score is None
    assert extra["unscored_reason"] == "disabled"
    score, extra = parse_ml_score_payload({"scored": False, "score": 0.0})
    assert score is None
    score, extra = parse_ml_score_payload({})
    assert score is None
    assert extra["unscored_reason"] == "missing_score"
    score, extra = parse_ml_score_payload(
        {"score": 0.0, "model_version": "fraud-gbm/v1"}
    )
    assert score == 0.0
    assert "unscored_reason" not in extra
    parsed, _ = parse_ml_score_payload({"score": 0.0, "model_version": "disabled"})
    with patch("decision_api.evaluate.score.settings") as s:
        s.score_blend_strategy = "average"
        assert blend_scores(80.0, parsed) == 80.0
        assert blend_scores(80.0, 0.0) == 40.0


def test_evaluate_hop_matrix_empty_url_tags_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_api.config import settings
    from decision_api.evaluate.score import (
        EVALUATE_HOP_UNCONFIGURED,
        tag_hop_unconfigured,
    )

    assert set(EVALUATE_HOP_UNCONFIGURED) == {
        "graph",
        "features",
        "ml",
        "opa",
        "counter",
        "location",
        "calibration",
    }
    for hop, (attr, tag) in EVALUATE_HOP_UNCONFIGURED.items():
        monkeypatch.setattr(settings, attr, "")
        tags: list[str] = []
        assert tag_hop_unconfigured(tags, hop) is True
        assert tags == [tag]
        monkeypatch.setattr(settings, attr, "http://hop.test")
        tags = []
        assert tag_hop_unconfigured(tags, hop) is False
        assert tags == []


def test_empty_opa_url_tags_unconfigured() -> None:
    from decision_api.opa_client import apply_opa_unconfigured

    tags: list[str] = []
    assert apply_opa_unconfigured(tags, "") is True
    assert tags == ["opa:unconfigured"]
    assert apply_opa_unconfigured(tags, "") is True
    assert tags == ["opa:unconfigured"]
    assert apply_opa_unconfigured(tags, "http://opa:8181") is False
    assert "opa:unavailable" not in tags
