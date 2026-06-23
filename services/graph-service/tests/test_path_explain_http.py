"""HTTP tests for path-explain endpoint (Q2-E03)."""

from fastapi.testclient import TestClient
from main import app


def test_path_explain_endpoint(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "")

    async def _explain(tenant_id, entity_id, depth=3, decay=0.5, *, to_entity_id=None, limit=10):
        return {
            "schema_id": "tarka.graph_path_explanation/v1",
            "tenant_id": tenant_id,
            "subject": entity_id,
            "target": to_entity_id,
            "paths": [
                {
                    "entity_id": "neighbor-1",
                    "distance": 1,
                    "propagated_risk_score": 50.0,
                    "path_description": "(root) -[USED]-> (neighbor-1)",
                    "hops": [
                        {"entity_id": "root", "labels": [], "relationship": None},
                        {"entity_id": "neighbor-1", "labels": [], "relationship": "USED"},
                    ],
                    "reasons": ["hop_distance:1"],
                }
            ],
            "risk_narrative": "Top outward risk exposures from root: neighbor-1 (d=1, score=50.0).",
            "summary": {"path_count": 1},
        }

    monkeypatch.setattr("main.explain_paths", _explain)
    with TestClient(app) as client:
        res = client.get(
            "/v1/analytics/path-explain",
            params={"tenant_id": "demo", "from_entity_id": "root"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["schema_id"] == "tarka.graph_path_explanation/v1"
    assert data["paths"][0]["path_description"]
