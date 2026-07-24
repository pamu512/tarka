from decision_api.graph_intel import graph_tags_from_risk


def test_neighbor_device_count_high_tag():
    tags = graph_tags_from_risk(
        {
            "risk_score": 10,
            "risk_factors": [],
            "neighbor_device_count": 3,
        }
    )
    assert "graph:neighbor_device_count_high" in tags


def test_neighbor_device_count_below_threshold_no_tag():
    tags = graph_tags_from_risk(
        {
            "risk_score": 10,
            "risk_factors": [],
            "neighbor_device_count": 2,
        }
    )
    assert "graph:neighbor_device_count_high" not in tags


def test_neighbor_device_count_missing_defaults_zero():
    tags = graph_tags_from_risk({"risk_score": 75, "risk_factors": []})
    assert "graph:high_risk_entity" in tags
    assert "graph:neighbor_device_count_high" not in tags
