"""Tests for graph path explanation assembly (Q2-E03)."""

from path_explain import assemble_path_explanation, validate_annotation_map


def test_assemble_path_explanation_ranks_by_score():
    rows = [
        {
            "entity_id": "far",
            "entity_labels": [],
            "propagated_risk_score": 25.0,
            "distance": 3,
            "node_chain": ["root", "mid", "far"],
            "rel_types": ["USED", "SHARED_WITH"],
        },
        {
            "entity_id": "near",
            "entity_labels": ["flagged"],
            "propagated_risk_score": 50.0,
            "distance": 1,
            "node_chain": ["root", "near"],
            "rel_types": ["USED"],
        },
    ]
    out = assemble_path_explanation("tenant-a", "root", rows, limit=5)
    assert out["schema_id"] == "tarka.graph_path_explanation/v1"
    assert out["tenant_id"] == "tenant-a"
    assert out["subject"] == "root"
    assert len(out["paths"]) == 2
    assert out["paths"][0]["entity_id"] == "near"
    assert "flagged" in out["risk_narrative"] or "near" in out["risk_narrative"]
    assert out["paths"][0]["hops"][0]["entity_id"] == "root"


def test_assemble_path_explanation_filters_target():
    rows = [
        {"entity_id": "a", "propagated_risk_score": 10, "distance": 1, "node_chain": ["r", "a"]},
        {"entity_id": "b", "propagated_risk_score": 20, "distance": 1, "node_chain": ["r", "b"]},
    ]
    out = assemble_path_explanation("t", "r", rows, to_entity_id="b")
    assert len(out["paths"]) == 1
    assert out["paths"][0]["entity_id"] == "b"
    assert out["target"] == "b"


def test_validate_annotation_map_trims_and_caps():
    raw = {" node-1 ": " note ", "": "x", "bad": ""}
    out = validate_annotation_map(raw)
    assert out == {"node-1": "note"}
