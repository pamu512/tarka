from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from graph_service.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    with TestClient(app) as c:
        yield c


def _subgraph():
    return {
        "nodes": [
            {
                "id": "buyer-demo",
                "labels": ["Person"],
                "properties": {
                    "last_trace_id": "tr-1",
                    "trace_ids": ["tr-1"],
                    "event_type": "login",
                },
            },
            {"id": "login:tr-1", "labels": ["Login"], "properties": {}},
        ],
        "edges": [
            {
                "from_id": "buyer-demo",
                "to_id": "login:tr-1",
                "type": "PERFORMED_LOGIN",
                "properties": {},
            }
        ],
    }


def test_decision_seed_404_without_markings(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [
                    {
                        "id": "dec:tr-1",
                        "labels": ["Decision"],
                        "properties": {"markings": ["desk"], "outcome": "deny"},
                    }
                ],
                "edges": [],
            }
        ),
    )
    hidden = client.get("/v1/entities/dec:tr-1", params={"tenant_id": "demo"})
    assert hidden.status_code == 404
    shown = client.get(
        "/v1/entities/dec:tr-1",
        params={"tenant_id": "demo"},
        headers={"X-Graph-Markings": "desk"},
    )
    assert shown.status_code == 200
    assert shown.json()["id"] == "dec:tr-1"


def test_get_entity_404(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph", AsyncMock(return_value={"nodes": [], "edges": []})
    )
    r = client.get("/v1/entities/ghost", params={"tenant_id": "demo"})
    assert r.status_code == 404
    assert r.json().get("detail") == "entity_not_found"


def test_get_entity_links_history(client, monkeypatch):
    monkeypatch.setattr("graph_service.main.query_subgraph", AsyncMock(return_value=_subgraph()))
    got = client.get("/v1/entities/buyer-demo", params={"tenant_id": "demo"})
    assert got.status_code == 200
    assert got.json()["labels"] == ["Person"]

    links = client.get("/v1/entities/buyer-demo/links", params={"tenant_id": "demo"})
    assert links.status_code == 200
    body = links.json()
    assert body["entity_id"] == "buyer-demo"
    assert any(e["type"] == "PERFORMED_LOGIN" for e in body["edges"])

    hist = client.get("/v1/entities/buyer-demo/history", params={"tenant_id": "demo"})
    assert hist.status_code == 200
    assert hist.json()["last_trace_id"] == "tr-1"
    assert hist.json()["trace_ids"] == ["tr-1"]
    assert hist.json()["decisions"] == []
    att = links.json().get("attention") or []
    assert any(row["entity_id"] == "login:tr-1" for row in att)
    assert all(row.get("attend_pack") is False for row in att)


def test_history_includes_resulted_in_decisions(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [
                    {
                        "id": "buyer-demo",
                        "labels": ["Person"],
                        "properties": {"last_trace_id": "tr-hop", "trace_ids": ["tr-hop"]},
                    },
                    {
                        "id": "dec:tr-hop",
                        "labels": ["Decision"],
                        "properties": {
                            "outcome": "deny",
                            "source": "evaluate",
                            "kind": "evaluate",
                            "trace_id": "tr-hop",
                            "created_at": "2026-08-31T00:00:00Z",
                            "markings": ["desk"],
                        },
                    },
                ],
                "edges": [
                    {
                        "from_id": "buyer-demo",
                        "to_id": "dec:tr-hop",
                        "type": "RESULTED_IN",
                        "properties": {},
                    }
                ],
            }
        ),
    )
    hidden = client.get("/v1/entities/buyer-demo/history", params={"tenant_id": "demo"})
    assert hidden.status_code == 200
    assert hidden.json()["decisions"] == []
    hist = client.get(
        "/v1/entities/buyer-demo/history",
        params={"tenant_id": "demo"},
        headers={"X-Graph-Markings": "desk"},
    )
    assert hist.status_code == 200
    rows = hist.json()["decisions"]
    assert rows == [
        {
            "id": "dec:tr-hop",
            "outcome": "deny",
            "source": "evaluate",
            "kind": "evaluate",
            "trace_id": "tr-hop",
            "created_at": "2026-08-31T00:00:00Z",
        }
    ]


def test_objects_attention_pack_bar(client, monkeypatch):
    async def _subgraph(tenant_id, entity_id, depth):
        if entity_id == "pay-hot":
            return {
                "nodes": [
                    {"id": "pay-hot", "labels": ["Payment"], "properties": {}},
                    {"id": "a", "labels": ["Person"], "risk_score": 10},
                    {"id": "b", "labels": ["Person"], "risk_score": 10},
                    {"id": "c", "labels": ["Person"], "risk_score": 10},
                ],
                "edges": [],
            }
        if entity_id == "ip:1.2.3.4":
            return {
                "nodes": [
                    {"id": "ip:1.2.3.4", "labels": ["Ip"], "properties": {}},
                    {"id": "a", "labels": ["Person"], "risk_score": 80},
                ],
                "edges": [],
            }
        return {"nodes": [], "edges": []}

    monkeypatch.setattr("graph_service.main.query_subgraph", _subgraph)
    r = client.post(
        "/v1/objects/attention",
        json={
            "tenant_id": "demo",
            "objects": [
                {"external_id": "pay-hot", "entity_type": "Payment", "on_this_event": True},
                {"external_id": "ip:1.2.3.4", "entity_type": "Ip", "on_this_event": True},
                {"external_id": "ghost", "entity_type": "Device", "on_this_event": True},
            ],
        },
    )
    assert r.status_code == 200, r.text
    by_id = {row["entity_id"]: row for row in r.json()["attention"]}
    assert by_id["pay-hot"]["attend_pack"] is True
    assert by_id["ip:1.2.3.4"]["attend_pack"] is False
    assert by_id["ghost"]["attend_pack"] is False
