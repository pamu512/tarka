"""GET /v1/slo smoke test."""

from fastapi.testclient import TestClient
from feature_service.main import app


def test_slo():
    with TestClient(app) as client:
        r = client.get("/v1/slo")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "feature-service"
    assert data["current"]["redis_velocity_configured"] is False
