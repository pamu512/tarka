"""Maturity Wave 1: y_label join + vertical pack kill criteria."""

from __future__ import annotations

from decision_api.label_join import (
    apply_y_labels,
    label_coverage_posture,
    y_label_from_ground_truth,
)
from decision_api.reliability_export import reliability_bins
from decision_api.vertical_packs import evaluate_kill_criteria, get_vertical_pack


def test_y_label_from_ground_truth():
    assert y_label_from_ground_truth("FRAUD") == "1"
    assert y_label_from_ground_truth("LEGITIMATE") == "0"
    assert y_label_from_ground_truth("nope") == ""


def test_y_label_store_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    from decision_api.y_label_store import _path, load_y_labels, merge_y_labels

    snap = merge_y_labels("demo", by_trace={"t1": "1"}, by_entity={"e1": "0"})
    assert snap["trace_labels"] == 1
    assert snap["entity_labels"] == 1
    loaded = load_y_labels("demo")
    assert loaded["by_trace"]["t1"] == "1"
    assert loaded["by_entity"]["e1"] == "0"
    merge_y_labels("demo", by_trace={"t2": "0"})
    again = load_y_labels("demo")
    assert again["by_trace"]["t1"] == "1"
    assert again["by_trace"]["t2"] == "0"
    # Path segment is hex digest — never the raw tenant / traversal payload.
    p = _path("../evil")
    assert p.parent == tmp_path.resolve()
    assert "evil" not in p.name
    assert ".." not in p.name


def test_reliability_bins_body_proxy_off_by_default():
    from decision_api.calibration_api import ReliabilityBinsBody

    body = ReliabilityBinsBody()
    assert body.allow_proxy_labels is False
    assert body.persist_labels is True


def test_apply_y_labels_and_posture():
    rows = [
        {
            "trace_id": "t1",
            "entity_id": "e1",
            "y_label": "",
            "proxy_label_from_decision": "1",
            "score": "80",
            "integrity_confidence": "0.8",
        },
        {
            "trace_id": "t2",
            "entity_id": "e2",
            "y_label": "",
            "proxy_label_from_decision": "0",
            "score": "20",
            "integrity_confidence": "0.2",
        },
    ]
    meta = apply_y_labels(rows, {"t1": "1"}, labels_by_entity={"e2": "0"})
    assert meta["y_label_joined"] == 2
    assert rows[0]["y_label"] == "1"
    assert rows[1]["y_label"] == "0"
    bins = reliability_bins(rows, n_bins=5, use_proxy_labels=False)
    assert bins["label_source"] == "y_label"
    assert bins["label_coverage"] == 1.0
    posture = label_coverage_posture(
        label_coverage=bins["label_coverage"], proxy_only=False
    )
    assert posture["healthy"] is True
    bad = label_coverage_posture(label_coverage=0.0, proxy_only=True)
    assert bad["healthy"] is False


def test_vertical_kill_criteria_blocks_underpowered():
    pack = get_vertical_pack("fintech")
    assert pack and pack.get("kill_criteria")
    gate = evaluate_kill_criteria(
        {"precision": 0.5, "recall": 0.5, "false_positive_rate": 0.1},
        pack["kill_criteria"],
        events_evaluated=10,
    )
    assert gate["promote_allowed"] is False
    assert "events_evaluated" in gate["blockers"][0]


def test_evaluate_shadow_request_helper():
    from decision_api.evaluate_shadow_request import is_shadow_evaluate_request

    assert is_shadow_evaluate_request({"shadow": True}) is True
    assert is_shadow_evaluate_request({"shadow": "true"}) is True
    assert is_shadow_evaluate_request({}) is False


def test_rule_precision_after_labels():
    from decision_api.rule_label_metrics import rule_precision_after_labels

    out = rule_precision_after_labels(
        [
            {
                "y_label": "0",
                "decision": "deny",
                "rule_hits": ["velocity_guard"],
            },
            {
                "y_label": "1",
                "decision": "deny",
                "rule_hits": ["velocity_guard"],
            },
            {"y_label": "", "decision": "allow", "rule_hits": ["noise"]},
        ],
        min_labeled_hits=1,
        min_coverage=0.2,
    )
    assert out["labeled_rows"] == 2
    assert out["posture"]["healthy"] is True
    row = next(r for r in out["rules"] if r["rule_id"] == "velocity_guard")
    assert row["labeled_hits"] == 2
    assert row["fp_hits"] == 1
    assert row["precision"] == 0.5


def test_partner_fusion_signals():
    from types import SimpleNamespace

    from decision_api.partner_fusion import (
        graph_writeback_hints,
        signals_to_feature_tags,
    )

    # ponytail: avoid vendors/ import (pulls tenacity); fusion only needs duck-typed attrs
    sigs = [
        SimpleNamespace(
            vendor_id="fingerprint",
            score_0_100=72.0,
            reason_codes=["bot"],
            raw_meta={"visitor_id": "vis-1"},
        )
    ]
    feats, tags, evidence = signals_to_feature_tags(sigs)
    assert feats["vendor_fingerprint_id"] == "vis-1"
    assert "vendor:fingerprint" in tags
    assert evidence
    hints = graph_writeback_hints(
        tenant_id="t1",
        entity_id="e1",
        transaction_id="tr1",
        tags=tags,
        features=feats,
    )
    assert hints["vertices"]
    assert hints["edges"]
