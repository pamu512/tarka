from graph_service.entity_risk_score import (
    entity_not_found_payload,
    p90_degree,
    score_entity_risk,
    stored_risk_view,
)


def _base(**over):
    kw = {
        "entity_id": "u1",
        "tags": [],
        "conn_count": 0,
        "flagged": 0,
        "community_size": 1,
        "shared_devices": 0,
        "neighbor_device_count": 0,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
        "peer_p90": None,
        "checkpoint": None,
        "profile": "standard",
        "hop_depth": 3,
        "freshness": None,
    }
    kw.update(over)
    return score_entity_risk(**kw)


def test_five_timestamped_edges_in_1h_flags_fast_growth():
    out = _base(relation_growth_1h=5)
    assert out["relation_growth_1h"] == 5
    assert any(x.startswith("fast_growth_1h:") for x in out["risk_factors"])
    assert out["risk_score"] >= 20
    assert out["scored"] is True


def test_untimestamped_growth_zero_does_not_flag():
    out = _base(conn_count=4, relation_growth_1h=0)
    assert out["risk_factors"] == []
    assert out["risk_score"] == 0
    assert out["scored"] is True


def test_high_degree_vs_peers_not_stacked_with_high_connectivity():
    out = _base(conn_count=12, peer_p90=8)
    factors = out["risk_factors"]
    assert any(x.startswith("high_degree_vs_peers:12:p90=8") for x in factors)
    assert not any(x.startswith("high_connectivity:") for x in factors)


def test_absolute_connectivity_when_no_peer_stats():
    out = _base(conn_count=12, peer_p90=None)
    assert any(x.startswith("high_connectivity:12") for x in out["risk_factors"])
    assert not any(x.startswith("high_degree_vs_peers:") for x in out["risk_factors"])


def test_not_found_payload_zero_score_unscored():
    out = entity_not_found_payload("missing", None, None, 3)
    assert out["risk_score"] == 0
    assert out["scored"] is False
    assert "entity_not_found" in out["risk_factors"]
    assert out["relation_count"] == 0
    assert out["relation_growth_1h"] == 0


def test_stored_view_unscored_is_null_not_zero():
    view = stored_risk_view({})
    assert view["scored"] is False
    assert view["risk_score"] is None
    assert view["relation_growth_1h"] is None


def test_stored_view_computed_zero_is_scored():
    view = stored_risk_view(
        {
            "risk_score": 0,
            "risk_computed_at": "2026-08-13T00:00:00Z",
            "relation_count": 2,
            "relation_growth_1h": 0,
            "relation_growth_24h": 0,
            "risk_factors": [],
        }
    )
    assert view["scored"] is True
    assert view["risk_score"] == 0


def test_p90_empty_is_none():
    assert p90_degree([]) is None
