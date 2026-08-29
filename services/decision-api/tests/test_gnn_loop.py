"""GNN label loop: receipts, export, holdout gate. Does not claim a GNN works."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.gnn_loop.export import export_labeled_rows
from decision_api.gnn_loop.snapshot import snapshot_at_evaluate, snapshot_from_written
from decision_api.gnn_loop.train import evaluate_holdout_gate, write_gate_artifact
from decision_api.y_label_store import load_label_records, merge_y_labels


def _ring_snapshot(*, fraud: bool, suffix: str) -> dict:
    """Cross-role same-device graph (heuristic_v1 fires) vs an isolated pair."""
    if fraud:
        return {
            "status": "graph:ok",
            "trace_id": f"t-fraud-{suffix}",
            "entity_id": f"buyer-{suffix}",
            "user_id": f"buyer-{suffix}",
            "role": "buyer",
            "vertices": [
                {"id": f"buyer-{suffix}", "kind": "user", "role": "buyer"},
                {"id": f"seller-{suffix}", "kind": "user", "role": "seller"},
                {"id": f"dev-{suffix}", "kind": "bridge", "role": "device"},
            ],
            "edges": [
                {
                    "src": f"buyer-{suffix}",
                    "dst": f"dev-{suffix}",
                    "type": "USES_DEVICE",
                },
                {
                    "src": f"seller-{suffix}",
                    "dst": f"dev-{suffix}",
                    "type": "USES_DEVICE",
                },
            ],
        }
    return {
        "status": "graph:ok",
        "trace_id": f"t-legit-{suffix}",
        "entity_id": f"buyer-{suffix}",
        "user_id": f"buyer-{suffix}",
        "role": "buyer",
        "vertices": [
            {"id": f"buyer-{suffix}", "kind": "user", "role": "buyer"},
            {"id": f"seller-{suffix}", "kind": "user", "role": "seller"},
        ],
        "edges": [
            {
                "src": f"buyer-{suffix}",
                "dst": f"seller-{suffix}",
                "type": "TRANSACTED",
            },
        ],
    }


def test_empty_graph_url_does_not_invent_a_graph():
    party = {
        "nodes": [
            {"id": "u1", "role": "buyer"},
            {"id": "d1", "role": "device"},
            {"id": "s1", "role": "seller"},
        ],
        "edges": [
            {"src": "u1", "dst": "d1", "type": "USES_DEVICE"},
            {"src": "s1", "dst": "d1", "type": "USES_DEVICE"},
        ],
    }
    snap = snapshot_at_evaluate(
        graph_service_url="",
        trace_id="trace-1",
        entity_id="u1",
        user_id="u1",
        role="buyer",
        written_subgraph=None,
        party_graph=party,
    )
    assert snap["status"] == "graph:missing"
    assert snap["edges"] == []
    assert snap["vertices"] == []
    assert snap["trace_id"] == "trace-1"
    assert snap["entity_id"] == "u1"
    assert snap["user_id"] == "u1"
    assert snap["role"] == "buyer"


def test_unlabeled_rows_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    receipts = [
        {
            **_ring_snapshot(fraud=True, suffix="a"),
            "trace_id": "t-labeled",
            "entity_id": "buyer-a",
        },
        {
            **_ring_snapshot(fraud=False, suffix="b"),
            "trace_id": "t-unlabeled",
            "entity_id": "buyer-b",
        },
    ]
    merge_y_labels(
        "acme", by_trace={"t-labeled": "1"}, why_by_trace={"t-labeled": "mule"}
    )
    rows = export_labeled_rows("acme", receipts)
    assert [r["trace_id"] for r in rows] == ["t-labeled"]
    assert rows[0]["y_label"] == "1"
    assert "t-unlabeled" not in {r["trace_id"] for r in rows}


def test_override_why_persists_onto_export_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    why = "analyst override: confirmed promo hub, not a delivery delay"
    merge_y_labels(
        "acme",
        by_trace={"t-why": "1"},
        why_by_trace={"t-why": why},
    )
    stored = load_label_records("acme")
    assert stored["why_by_trace"]["t-why"] == why
    receipt = {
        **_ring_snapshot(fraud=True, suffix="w"),
        "trace_id": "t-why",
        "entity_id": "buyer-w",
    }
    rows = export_labeled_rows("acme", [receipt])
    assert len(rows) == 1
    assert rows[0]["y_label"] == "1"
    assert rows[0]["why"] == why
    assert "dispute_outcome" in rows[0]
    assert "chargeback_class" in rows[0]


def test_holdout_gate_blocks_serve_when_heuristic_wins(tmp_path):
    # heuristic_v1 separates these; a constant/inverted scorer does not.
    holdout = []
    for i in range(6):
        holdout.append(
            {
                "subgraph_snapshot": _ring_snapshot(fraud=True, suffix=f"h{i}"),
                "y_label": "1",
            }
        )
        holdout.append(
            {
                "subgraph_snapshot": _ring_snapshot(fraud=False, suffix=f"l{i}"),
                "y_label": "0",
            }
        )
    # Model scores inverted vs the ring structure heuristic_v1 uses.
    model_scores = [0.1 if r["y_label"] == "1" else 0.9 for r in holdout]
    gate = evaluate_holdout_gate(holdout, model_scores)
    assert gate["serve_allowed"] is False
    assert gate["beats_heuristic"] is False
    assert gate["baseline"] == "heuristic_v1"
    path = write_gate_artifact(tmp_path / "gnn_serve_gate.json", gate)
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["serve_allowed"] is False


def test_edgeless_receipt_is_not_trainable(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    merge_y_labels(
        "acme", by_trace={"t-empty": "1"}, why_by_trace={"t-empty": "override"}
    )
    receipt = {
        "status": "graph:ok",
        "trace_id": "t-empty",
        "entity_id": "u1",
        "user_id": "u1",
        "role": "buyer",
        "vertices": [{"id": "u1", "kind": "user", "role": "buyer"}],
        "edges": [],
    }
    rows = export_labeled_rows("acme", [receipt])
    assert len(rows) == 1
    assert rows[0]["trainable"] is False


def test_late_chargeback_fields_on_export(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    merge_y_labels(
        "acme",
        by_trace={"t-cb": "1"},
        why_by_trace={"t-cb": "override first"},
        dispute_outcome_by_trace={"t-cb": "fraud_confirmed"},
        chargeback_class_by_trace={"t-cb": "FRAUD"},
    )
    receipt = {**_ring_snapshot(fraud=True, suffix="cb"), "trace_id": "t-cb"}
    rows = export_labeled_rows("acme", [receipt])
    assert rows[0]["why"] == "override first"
    assert rows[0]["dispute_outcome"] == "fraud_confirmed"
    assert rows[0]["chargeback_class"] == "FRAUD"


def test_url_set_but_no_written_subgraph_does_not_use_party_graph():
    snap = snapshot_at_evaluate(
        graph_service_url="http://graph.example",
        trace_id="t1",
        entity_id="u1",
        user_id="u1",
        role="buyer",
        written_subgraph=None,
        party_graph={
            "nodes": [{"id": "u1", "role": "buyer"}, {"id": "d1", "role": "device"}],
            "edges": [{"src": "u1", "dst": "d1", "type": "USES_DEVICE"}],
        },
    )
    assert snap["status"] == "graph:unavailable"
    assert snap["edges"] == []
    assert snap["vertices"] == []


@pytest.mark.asyncio
async def test_serve_refuses_when_gate_blocks(tmp_path, monkeypatch):
    from decision_api.gnn_loop.serve import score_graph_risk

    monkeypatch.setenv("GNN_LOOP_GATE_PATH", str(tmp_path / "gnn_serve_gate.json"))
    write_gate_artifact(
        tmp_path / "gnn_serve_gate.json",
        {
            "serve_allowed": False,
            "beats_heuristic": False,
            "baseline": "heuristic_v1",
            "reason": "holdout_did_not_beat_heuristic_v1",
            "model_auc": 0.2,
            "heuristic_auc": 0.9,
        },
    )
    out = await score_graph_risk("t", "e1")
    assert out is None


def test_same_id_different_vtype_are_two_vertices():
    snap = snapshot_from_written(
        {
            "nodes": [
                {
                    "id": "abc",
                    "vtype": "user",
                    "labels": ["user"],
                    "properties": {
                        "tenant_id": "acme",
                        "vtype": "user",
                        "roles": ["buyer"],
                    },
                },
                {
                    "id": "abc",
                    "vtype": "device",
                    "labels": ["device"],
                    "properties": {"tenant_id": "acme", "vtype": "device"},
                },
            ],
            "edges": [
                {
                    "from_id": "abc",
                    "to_id": "abc",
                    "type": "USED",
                    "from_vtype": "user",
                    "to_vtype": "device",
                }
            ],
        },
        trace_id="t-hop",
        entity_id="abc",
        user_id="abc",
        role="buyer",
        tenant_id="acme",
    )
    keys = {(v["tenant_id"], v["vtype"], v["id"]) for v in snap["vertices"]}
    assert keys == {("acme", "user", "abc"), ("acme", "device", "abc")}
    assert {v["kind"] for v in snap["vertices"]} == {"user", "bridge"}
    user = next(v for v in snap["vertices"] if v["vtype"] == "user")
    assert user["role"] == "buyer"
    assert snap["role"] == "buyer"
    assert snap["edges"][0]["type"] == "USED"
    assert snap["edges"][0]["from_id"] == "abc"
    assert snap["edges"][0]["to_id"] == "abc"


def test_named_used_edge_survives_export(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    merge_y_labels(
        "acme", by_trace={"t-used": "1"}, why_by_trace={"t-used": "override"}
    )
    receipt = snapshot_from_written(
        {
            "vertices": [
                {"id": "u1", "vtype": "user", "kind": "user"},
                {"id": "d1", "vtype": "device", "kind": "bridge"},
            ],
            "edges": [{"from_id": "u1", "to_id": "d1", "type": "USED"}],
        },
        trace_id="t-used",
        entity_id="u1",
        user_id="u1",
        role="buyer",
        tenant_id="acme",
    )
    rows = export_labeled_rows("acme", [receipt])
    assert len(rows) == 1
    assert rows[0]["trainable"] is True
    assert rows[0]["subgraph_snapshot"]["edges"][0]["type"] == "USED"
    assert rows[0]["subgraph_snapshot"]["role"] == "buyer"


def test_evaluate_role_is_required_on_receipt():
    snap = snapshot_at_evaluate(
        graph_service_url="",
        trace_id="t-role",
        entity_id="u1",
        user_id="u1",
        role="member",
        tenant_id="acme",
        written_subgraph=None,
        party_graph={"nodes": [{"id": "u1", "role": "diner"}]},
    )
    assert snap["status"] == "graph:missing"
    assert snap["role"] == "member"
    assert snap["vertices"] == []
