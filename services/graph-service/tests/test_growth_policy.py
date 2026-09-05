from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from graph_service.growth_policy import count_growth, parse_growth_windows, threshold_for
from graph_service.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.delenv("GRAPH_GROWTH_WINDOWS", raising=False)
    with TestClient(app) as c:
        yield c


def test_parse_growth_windows_default_and_drop_unknown():
    assert parse_growth_windows(None) == [("1h", 5), ("24h", 15)]
    assert parse_growth_windows("1h:5,6h:8,nope:1") == [("1h", 5), ("6h", 8)]
    assert parse_growth_windows("") == [("1h", 5), ("24h", 15)]


def test_parse_growth_windows_empty_after_unknown_uses_default():
    assert parse_growth_windows("nope:1,also:2") == [("1h", 5), ("24h", 15)]


def test_count_growth_window_not_hardcoded_1h_only():
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    stamps = [now - timedelta(minutes=10), now - timedelta(hours=3)]
    assert count_growth(stamps, "1h", now=now) == 1
    assert count_growth(stamps, "6h", now=now) == 2
    assert count_growth(stamps, "5m", now=now) == 0


def test_count_growth_excludes_untimestamped():
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    stamps = [now - timedelta(minutes=10), None, "", "not-a-date"]
    assert count_growth(stamps, "1h", now=now) == 1


def test_threshold_for_default_and_missing(monkeypatch):
    monkeypatch.delenv("GRAPH_GROWTH_WINDOWS", raising=False)
    assert threshold_for("1h") == 5
    assert threshold_for("24h") == 15
    assert threshold_for("6h") is None
    assert threshold_for("1h", [("6h", 8)]) is None
    assert threshold_for("6h", [("6h", 8)]) == 8


def test_growth_policy_endpoint_default_windows(client):
    r = client.get("/v1/graph/growth-policy")
    assert r.status_code == 200
    assert r.json() == {
        "windows": [
            {"window": "1h", "threshold": 5},
            {"window": "24h", "threshold": 15},
        ]
    }


def test_relation_growth_missing_entity_count_null(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(return_value={"nodes": [], "edges": []}),
    )
    r = client.get("/v1/entities/ghost/relation-growth", params={"tenant_id": "demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["entity_id"] == "ghost"
    assert body["tenant_id"] == "demo"
    assert body["windows"] == [
        {"window": "1h", "count": None, "threshold": 5},
        {"window": "24h", "count": None, "threshold": 15},
    ]


def test_relation_growth_omits_unknown_window(client, monkeypatch):
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [{"id": "u1", "labels": ["Person"], "properties": {}}],
                "edges": [],
            }
        ),
    )
    r = client.get(
        "/v1/entities/u1/relation-growth",
        params={"tenant_id": "demo", "windows": "1h,nope,24h"},
    )
    assert r.status_code == 200
    windows = r.json()["windows"]
    assert [w["window"] for w in windows] == ["1h", "24h"]
    assert all(w["count"] == 0 for w in windows)


def test_relation_growth_counts_incident_coalesced_stamps(client, monkeypatch):
    monkeypatch.setenv("GRAPH_GROWTH_WINDOWS", "1h:5,6h:8")
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    monkeypatch.setattr(
        "graph_service.growth_policy.datetime",
        type("frozen", (), {"now": staticmethod(lambda tz=None: now)}),
    )
    monkeypatch.setattr(
        "graph_service.main.query_subgraph",
        AsyncMock(
            return_value={
                "nodes": [
                    {"id": "u1", "labels": ["Person"], "properties": {}},
                    {"id": "d1", "labels": ["Device"], "properties": {}},
                    {"id": "d2", "labels": ["Device"], "properties": {}},
                    {"id": "d3", "labels": ["Device"], "properties": {}},
                ],
                "edges": [
                    {
                        "from_id": "u1",
                        "to_id": "d1",
                        "type": "USES_DEVICE",
                        "properties": {
                            "observed_at": (now - timedelta(minutes=10)).isoformat()
                        },
                    },
                    {
                        "from_id": "u1",
                        "to_id": "d2",
                        "type": "USES_DEVICE",
                        "properties": {
                            "created_at": (now - timedelta(hours=3)).isoformat()
                        },
                    },
                    {
                        "from_id": "u1",
                        "to_id": "d3",
                        "type": "USES_DEVICE",
                        "properties": {},
                    },
                ],
            }
        ),
    )
    r = client.get(
        "/v1/entities/u1/relation-growth",
        params={"tenant_id": "demo", "windows": "1h,6h"},
    )
    assert r.status_code == 200
    by_w = {w["window"]: w for w in r.json()["windows"]}
    assert by_w["1h"] == {"window": "1h", "count": 1, "threshold": 5}
    assert by_w["6h"] == {"window": "6h", "count": 2, "threshold": 8}
