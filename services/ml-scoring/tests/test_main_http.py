"""Smoke coverage for ``ml_scoring.main`` (FastAPI app) — restores cov on ``main.py`` after heuristic split."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ml_scoring.main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model_version" in body


def test_slo() -> None:
    with TestClient(app) as client:
        r = client.get("/v1/slo")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "ml-scoring"
    assert "current" in data


def test_score_when_ml_disabled() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/v1/score",
            json={
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_type": "pay",
                "features": {"amount": 50.0},
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["score"] == 0.0
    assert data["model_version"] == "disabled"


def test_models_list() -> None:
    with TestClient(app) as client:
        r = client.get("/v1/models")
    assert r.status_code == 200
    assert "models" in r.json()


def test_adaptive_endpoints() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/adaptive/stats").status_code == 200
        assert client.get("/v1/adaptive/drift").status_code == 200
        assert client.get("/v1/adaptive/thresholds").status_code == 200
        reset = client.post("/v1/adaptive/reset")
        assert reset.status_code == 200
        assert reset.json().get("ok") is True
