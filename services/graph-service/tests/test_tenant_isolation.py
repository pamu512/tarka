"""Two-tenant graph read isolation under TENANT_BINDING_REQUIRED."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_KEY_A = "graph-iso-a"
_KEY_B = "graph-iso-b"
_TENANT_A = "tenant_alpha"
_TENANT_B = "tenant_beta"


@pytest.fixture
def graph_iso_client(monkeypatch):
    monkeypatch.setenv("API_KEYS", f"{_KEY_A},{_KEY_B}")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_KEY_A: [_TENANT_A], _KEY_B: [_TENANT_B]}),
    )
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("GRAPH_BACKEND", "janusgraph")

    with patch(
        "graph_service.main.search_entities",
        new_callable=AsyncMock,
        return_value=([], False),
    ):
        from graph_service.main import app

        with TestClient(app) as client:
            yield client


def test_graph_search_cross_tenant_forbidden(graph_iso_client):
    cross = graph_iso_client.get(
        "/v1/entities/search",
        params={"tenant_id": _TENANT_A, "q": "x"},
        headers={"X-API-Key": _KEY_B},
    )
    assert cross.status_code == 403, cross.text
    assert "outside caller scope" in cross.json()["detail"]

    own = graph_iso_client.get(
        "/v1/entities/search",
        params={"tenant_id": _TENANT_B, "q": "x"},
        headers={"X-API-Key": _KEY_B},
    )
    assert own.status_code == 200, own.text
    assert own.json().get("entities") == []
