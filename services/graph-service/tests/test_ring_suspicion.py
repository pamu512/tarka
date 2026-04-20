from fastapi.testclient import TestClient
from graph_service.main import app


def test_ring_suspicion_endpoint_returns_mule_summary(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setattr("graph_service.main._valid_api_keys", None)

    async def _risk(tenant_id, entity_id):
        return {
            "entity_id": entity_id,
            "risk_score": 62.0,
            "risk_factors": ["connected_flagged_3"],
        }

    async def _rings(tenant_id, min_ring_size=3):
        return [
            {
                "ring_members": ["acct-1", "acct-2"],
                "ring_size": 2,
                "relationships": ["USED"],
                "aggregate_tags": ["shared_device"],
            }
        ]

    monkeypatch.setattr(
        "graph_service.main.compute_entity_risk",
        _risk,
    )
    monkeypatch.setattr(
        "graph_service.main.detect_fraud_rings",
        _rings,
    )
    with TestClient(app) as client:
        res = client.get("/v1/analytics/ring-suspicion", params={"tenant_id": "demo", "entity_id": "acct-1"})
    assert res.status_code == 200
    data = res.json()
    assert data["entity_id"] == "acct-1"
    assert data["suspicion_level"] in {"medium", "high"}
    assert "entity_present_in_detected_ring" in data["reasons"]
