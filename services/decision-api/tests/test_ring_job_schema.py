"""G2.1: offline ring job request/response + never sync on evaluate."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_api.gnn_loop.snapshot import snapshot_at_evaluate
from decision_api.ring_job import (
    JOB_REQUEST_SCHEMA,
    JOB_RESPONSE_SCHEMA,
    run_ring_job,
    validate_ring_request,
)

_EVALUATE_DIR = Path(__file__).resolve().parents[1] / "src/decision_api/evaluate"
_SYNC_NEEDLES = (
    "run_ring_job",
    "validate_ring_request",
    "from decision_api.ring_job",
    "import ring_job",
)


def _export_subgraph() -> dict:
    return {
        "nodes": [
            {"id": "a", "role": "buyer"},
            {"id": "b", "role": "device"},
            {"id": "c", "role": "seller"},
        ],
        "edges": [
            {"src": "a", "dst": "b", "type": "USES_DEVICE"},
            {"src": "a", "dst": "c", "type": "TRANSACTED"},
        ],
    }


def _labels() -> list[dict]:
    return [
        {"entity_id": "a", "y_label": "1"},
        {"entity_id": "c", "y_label": "0"},
    ]


def test_invalid_schema_id_raises() -> None:
    with pytest.raises(ValueError, match="schema_id"):
        validate_ring_request(
            {"schema_id": "tarka.nope/v1", "tenant_id": "t1", "edges": []}
        )


def test_missing_tenant_id_raises() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        validate_ring_request(
            {"schema_id": JOB_REQUEST_SCHEMA, "edges": [{"src": "a", "dst": "b"}]}
        )


def test_invalid_subgraph_shape_raises() -> None:
    with pytest.raises(ValueError, match="subgraph"):
        validate_ring_request(
            {
                "schema_id": JOB_REQUEST_SCHEMA,
                "tenant_id": "t1",
                "subgraph": "not-a-graph",
                "labels": _labels(),
            }
        )


def test_subgraph_without_labels_raises() -> None:
    with pytest.raises(ValueError, match="labels"):
        validate_ring_request(
            {
                "schema_id": JOB_REQUEST_SCHEMA,
                "tenant_id": "t1",
                "subgraph": _export_subgraph(),
            }
        )


def test_request_accepts_export_subgraph_and_labels() -> None:
    req = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "subgraph": _export_subgraph(),
        "labels": _labels(),
    }
    got = validate_ring_request(req)
    assert got["schema_id"] == JOB_REQUEST_SCHEMA
    assert got["tenant_id"] == "t1"
    assert got["subgraph"]["edges"][0]["src"] == "a"
    assert got["labels"][0]["y_label"] == "1"


def test_request_accepts_edges_derived_from_export_rows() -> None:
    req = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "export": [
            {
                "entity_id": "a",
                "y_label": "1",
                "subgraph_snapshot": {
                    "vertices": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                    "edges": [
                        {"src": "a", "dst": "b", "type": "USES_DEVICE"},
                        {"src": "a", "dst": "c", "type": "TRANSACTED"},
                    ],
                },
            }
        ],
    }
    validate_ring_request(req)
    out = run_ring_job(req)
    assert out["schema_id"] == JOB_RESPONSE_SCHEMA
    assert out["tenant_id"] == "t1"
    assert out["live"] is False
    assert out["tags"][0]["entity_id"] == "a"
    assert "ring_score" in out["tags"][0]


def test_response_schema_locked_live_false_no_flag_deny() -> None:
    req = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "acme",
        "subgraph": _export_subgraph(),
        "labels": _labels(),
    }
    out = run_ring_job(req)
    assert out["schema_id"] == JOB_RESPONSE_SCHEMA
    assert out["tenant_id"] == "acme"
    assert out["live"] is False
    assert isinstance(out["tags"], list)
    assert isinstance(out["ring_score"], list)
    blob = str(out).upper()
    assert "FLAG" not in blob
    assert "DENY" not in blob
    assert "ALLOW" not in blob


def test_evaluate_path_does_not_call_ring_job_sync() -> None:
    paths = list(_EVALUATE_DIR.glob("*.py"))
    paths.append(
        Path(__file__).resolve().parents[1] / "src/decision_api/eval_steps.py"
    )
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/eval_dag.py")
    paths.append(Path(__file__).resolve().parents[1] / "src/decision_api/main.py")
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in _SYNC_NEEDLES:
            assert needle not in text, f"{path.name} must not call ring job sync"


def test_empty_graph_url_hops_off_job_does_not_invent_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAPH_SERVICE_URL", "")
    snap = snapshot_at_evaluate(
        graph_service_url="",
        trace_id="tr-1",
        entity_id="u1",
        user_id="u1",
        role="buyer",
        written_subgraph=None,
        party_graph={
            "nodes": [{"id": "ghost"}],
            "edges": [{"src": "ghost", "dst": "invented"}],
        },
    )
    assert snap["status"] == "graph:missing"
    assert snap["edges"] == []
    assert snap["vertices"] == []

    out = run_ring_job(
        {
            "schema_id": JOB_REQUEST_SCHEMA,
            "tenant_id": "t1",
            "subgraph": _export_subgraph(),
            "labels": _labels(),
        }
    )
    ids = {t["entity_id"] for t in out["tags"]}
    assert "ghost" not in ids
    assert "invented" not in ids
    assert ids <= {"a", "b", "c"}
    assert out["live"] is False
