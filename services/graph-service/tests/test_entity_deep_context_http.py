from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from graph_service.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    with TestClient(app) as c:
        yield c


def test_entity_deep_context_404(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(return_value={"nodes": [], "edges": []}),
    )
    monkeypatch.setattr(
        "graph_service.main.query_entity_deep_context", AsyncMock(return_value=None)
    )
    r = client.get("/v1/entities/ghost-entity/deep-context", params={"tenant_id": "demo"})
    assert r.status_code == 404
    assert r.json().get("detail") == "entity_not_found"


def test_deep_context_decision_seed_404_without_markings(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [
                    {
                        "id": "dec:hidden",
                        "labels": ["Decision"],
                        "properties": {"markings": ["desk"], "outcome": "deny"},
                    }
                ],
                "edges": [],
            }
        ),
    )
    monkeypatch.setattr(
        "graph_service.main.query_entity_deep_context",
        AsyncMock(return_value={"entity_id": "dec:hidden", "tenant_id": "demo"}),
    )
    monkeypatch.setattr("graph_service.main.compute_entity_risk", AsyncMock(return_value={}))
    hidden = client.get("/v1/entities/dec:hidden/deep-context", params={"tenant_id": "demo"})
    assert hidden.status_code == 404
    shown = client.get(
        "/v1/entities/dec:hidden/deep-context",
        params={"tenant_id": "demo"},
        headers={"X-Graph-Markings": "desk"},
    )
    assert shown.status_code == 200


def test_entity_deep_context_includes_risk_history(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [{"id": "acme", "labels": ["Person"], "properties": {}}],
                "edges": [],
            }
        ),
    )
    monkeypatch.setattr(
        "graph_service.main.query_entity_deep_context",
        AsyncMock(
            return_value={
                "entity_id": "acme",
                "tenant_id": "demo",
                "historical_transactions": [],
                "ip_addresses": [],
            }
        ),
    )
    monkeypatch.setattr(
        "graph_service.main.compute_entity_risk",
        AsyncMock(return_value={"risk_score": 42.5, "risk_factors": ["velocity"]}),
    )
    r = client.get("/v1/entities/acme/deep-context", params={"tenant_id": "demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["entity_id"] == "acme"
    assert len(body["risk_history"]) == 1
    assert body["risk_history"][0]["risk_score"] == 42.5
    assert "velocity" in body["risk_history"][0]["risk_factors"]
