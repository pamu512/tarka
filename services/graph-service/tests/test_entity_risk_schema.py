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
