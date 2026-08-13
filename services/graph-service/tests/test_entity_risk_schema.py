from graph_service.schemas import EntityRiskResponse


def test_entity_risk_response_includes_neighbor_device_count():
    model = EntityRiskResponse.model_validate(
        {
            "entity_id": "u1",
            "risk_score": 42.0,
            "risk_factors": ["moderate_connectivity:5"],
            "connected_flagged_count": 1,
            "community_size": 4,
            "neighbor_device_count": 5,
        }
    )
    assert model.neighbor_device_count == 5
    dumped = model.model_dump()
    assert dumped["neighbor_device_count"] == 5


def test_entity_risk_response_includes_scored_and_growth():
    model = EntityRiskResponse.model_validate(
        {
            "entity_id": "u1",
            "risk_score": 20.0,
            "risk_factors": ["fast_growth_1h:5"],
            "connected_flagged_count": 0,
            "community_size": 1,
            "neighbor_device_count": 0,
            "scored": True,
            "relation_count": 5,
            "relation_growth_1h": 5,
            "relation_growth_24h": 5,
        }
    )
    assert model.scored is True
    assert model.relation_count == 5
    assert model.relation_growth_1h == 5
    assert model.relation_growth_24h == 5
    dumped = model.model_dump()
    assert dumped["scored"] is True
    assert dumped["relation_growth_1h"] == 5


def test_entity_risk_response_defaults_scored_and_growth():
    model = EntityRiskResponse.model_validate(
        {
            "entity_id": "missing",
            "risk_score": 0,
            "risk_factors": ["entity_not_found"],
        }
    )
    assert model.scored is False
    assert model.relation_count == 0
    assert model.relation_growth_1h == 0
    assert model.relation_growth_24h == 0
