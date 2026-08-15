from unittest.mock import AsyncMock

import pytest


def _top_row(eid: str, score: float) -> dict:
    return {
        "entity_id": eid,
        "labels": ["Account"],
        "risk_score": score,
        "risk_factors": [],
        "risk_computed_at": "2026-08-13T00:00:00Z",
        "relation_count": 3,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
    }


def test_top_returns_mock_order(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    rows = [_top_row("a", 90.0), _top_row("b", 40.0)]
    monkeypatch.setattr("graph_service.main.list_entity_risk_top", AsyncMock(return_value=rows))
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        data = client.get(
            "/v1/analytics/entity-risk/top",
            params={"tenant_id": "t", "limit": 10, "min_score": 0},
        ).json()
    assert [e["entity_id"] for e in data["entities"]] == ["a", "b"]


def test_limit_clamp():
    from graph_service.entity_risk_writeback import clamp_top_limit, clamp_refresh_limit

    assert clamp_top_limit(0) == 1
    assert clamp_top_limit(999) == 200
    assert clamp_refresh_limit(0) == 1
    assert clamp_refresh_limit(99999) == 20000


def test_refresh_entity_404(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from graph_service.entity_risk_score import entity_not_found_payload

    monkeypatch.setattr(
        "graph_service.main.compute_entity_risk",
        AsyncMock(return_value=entity_not_found_payload("x", None, None, 3)),
    )
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        r = client.post(
            "/v1/analytics/entity-risk/refresh", json={"tenant_id": "t", "entity_id": "x"}
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_refresh_tenant_truncated_writes_p90(monkeypatch):
    from graph_service.entity_risk_writeback import refresh_tenant

    found = {
        "risk_score": 10,
        "risk_factors": [],
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
        "scored": True,
        "primary_label": "Account",
    }
    monkeypatch.setattr(
        "graph_service.entity_risk_writeback.scan_tenant_entity_ids",
        AsyncMock(return_value=(["a", "b", "c"], True)),
    )
    monkeypatch.setattr(
        "graph_service.entity_risk_writeback.compute_entity_risk",
        AsyncMock(
            side_effect=lambda t, e, **k: {
                **found,
                "entity_id": e,
                "relation_count": 10 if e == "a" else 1,
            }
        ),
    )
    monkeypatch.setattr("graph_service.entity_risk_writeback.persist_entity_risk", AsyncMock())
    upsert = AsyncMock()
    monkeypatch.setattr("graph_service.entity_risk_writeback.upsert_graph_risk_stats", upsert)
    out = await refresh_tenant("t", limit=2)
    assert out["truncated"] is True
    upsert.assert_awaited()


@pytest.mark.asyncio
async def test_list_entity_risk_top_query_filters_unscored(monkeypatch):
    captured: dict = {}

    class _Result:
        async def data(self):
            return [
                {
                    "entity_id": "scored",
                    "labels": ["Account"],
                    "risk_score": 12.0,
                    "risk_factors": [],
                    "risk_computed_at": "2026-08-13T00:00:00Z",
                    "relation_count": 1,
                    "relation_growth_1h": 0,
                    "relation_growth_24h": 0,
                }
            ]

    class _Session:
        async def run(self, q, **kwargs):
            captured["q"] = q
            captured["kwargs"] = kwargs
            return _Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Driver:
        def session(self):
            return _Session()

    monkeypatch.setattr("graph_service.neo4j_client.get_driver", AsyncMock(return_value=_Driver()))
    from graph_service.neo4j_client import list_entity_risk_top

    rows = await list_entity_risk_top("t", limit=10, min_score=0)
    assert "risk_computed_at IS NOT NULL" in captured["q"]
    assert all(r.get("risk_computed_at") for r in rows)
    assert [r["entity_id"] for r in rows] == ["scored"]
