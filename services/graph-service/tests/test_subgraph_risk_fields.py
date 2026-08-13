from graph_service.entity_risk_score import decorate_subgraph_node


def test_decorate_unscored_nulls():
    node = {"id": "u1", "labels": ["Account"], "properties": {"external_id": "u1"}}
    out = decorate_subgraph_node(node)
    assert out["scored"] is False
    assert out["risk_score"] is None


def test_decorate_scored_zero():
    node = {
        "id": "u1",
        "labels": ["Account"],
        "properties": {
            "risk_score": 0,
            "risk_computed_at": "2026-08-13T00:00:00Z",
            "relation_count": 1,
            "relation_growth_1h": 0,
            "relation_growth_24h": 0,
            "risk_factors": [],
        },
    }
    out = decorate_subgraph_node(node)
    assert out["scored"] is True
    assert out["risk_score"] == 0
