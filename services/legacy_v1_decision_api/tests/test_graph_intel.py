from decision_api.graph_intel import graph_score_delta, graph_tags_from_risk


def test_graph_score_delta_scale():
    assert graph_score_delta(0) == 0.0
    assert graph_score_delta(50) == 10.0
    assert graph_score_delta(100) == 20.0


def test_graph_tags_from_risk_levels_and_factors():
    payload = {
        "risk_score": 75,
        "risk_factors": ["connected_flagged:2", "shared_devices:1"],
    }
    tags = graph_tags_from_risk(payload)
    assert "graph:high_risk_entity" in tags
    assert "graph:connected_flagged:2" in tags
    assert "graph:shared_devices:1" in tags
