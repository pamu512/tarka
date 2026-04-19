"""Smoke: GET /v1/slo on case-api."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_slo_endpoint():
    with patch("case_api.main.init_db", new_callable=AsyncMock):
        from case_api.main import app

        with TestClient(app) as client:
            r = client.get("/v1/slo")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "case-api"
    assert "current" in data
