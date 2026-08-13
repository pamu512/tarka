import pytest
from unittest.mock import AsyncMock, patch
from graph_service.entity_risk_score import entity_not_found_payload
from graph_service.entity_risk_writeback import persist_entity_risk


@pytest.mark.asyncio
async def test_persist_skips_not_found():
    setter = AsyncMock()
    with patch("graph_service.entity_risk_writeback.set_entity_risk_properties", setter):
        await persist_entity_risk("t", "missing", entity_not_found_payload("missing", None, None, 3))
    setter.assert_not_called()


@pytest.mark.asyncio
async def test_persist_sets_found_payload():
    setter = AsyncMock()
    payload = {
        "entity_id": "u1",
        "risk_score": 20,
        "risk_factors": ["fast_growth_1h:5"],
        "relation_count": 5,
        "relation_growth_1h": 5,
        "relation_growth_24h": 5,
        "scored": True,
    }
    with patch("graph_service.entity_risk_writeback.set_entity_risk_properties", setter):
        await persist_entity_risk("t", "u1", payload)
    setter.assert_awaited()
    kwargs = setter.await_args.kwargs if setter.await_args.kwargs else {}
    # positional: tenant_id, entity_id, props
    props = setter.await_args.args[2]
    assert props["risk_score"] == 20
    assert props["relation_growth_1h"] == 5
    assert "risk_computed_at" in props


@pytest.mark.asyncio
async def test_persist_swallows_set_errors():
    setter = AsyncMock(side_effect=RuntimeError("neo4j down"))
    payload = {
        "entity_id": "u1",
        "risk_score": 20,
        "risk_factors": ["fast_growth_1h:5"],
        "relation_count": 5,
        "relation_growth_1h": 5,
        "relation_growth_24h": 5,
        "scored": True,
    }
    with patch("graph_service.entity_risk_writeback.set_entity_risk_properties", setter):
        await persist_entity_risk("t", "u1", payload)


def test_get_entity_risk_write_through_found(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    async def _compute(tenant_id, entity_id, checkpoint=None):
        return {"entity_id": entity_id, "risk_score": 20, "risk_factors": ["fast_growth_1h:5"],
                "connected_flagged_count": 0, "community_size": 1, "neighbor_device_count": 0,
                "scored": True, "relation_count": 5, "relation_growth_1h": 5, "relation_growth_24h": 5}
    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr("graph_service.main.score_graph_risk_beta", AsyncMock(return_value=None))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "u1"})
    assert r.status_code == 200
    assert r.json()["scored"] is True
    persist.assert_awaited()


def test_get_entity_risk_not_found_does_not_persist(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    async def _compute(tenant_id, entity_id, checkpoint=None):
        from graph_service.entity_risk_score import entity_not_found_payload
        return entity_not_found_payload(entity_id, checkpoint, None, 3)

    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr("graph_service.main.score_graph_risk_beta", AsyncMock(return_value=None))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "missing"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] == 0
    assert body["scored"] is False
    persist.assert_not_awaited()


def test_get_entity_risk_not_found_ignores_high_beta(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    async def _compute(tenant_id, entity_id, checkpoint=None):
        from graph_service.entity_risk_score import entity_not_found_payload
        return entity_not_found_payload(entity_id, checkpoint, None, 3)

    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr(
        "graph_service.main.score_graph_risk_beta",
        AsyncMock(return_value={"risk_score": 99, "reasons": ["x"]}),
    )
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "missing"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] == 0
    assert body["scored"] is False
    assert "entity_not_found" in body["risk_factors"]
    persist.assert_not_awaited()


def test_get_entity_risk_beta_keeps_compute_growth(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    async def _compute(tenant_id, entity_id, checkpoint=None):
        return {
            "entity_id": entity_id,
            "risk_score": 20,
            "risk_factors": ["fast_growth_1h:5"],
            "connected_flagged_count": 0,
            "community_size": 1,
            "neighbor_device_count": 0,
            "scored": True,
            "relation_count": 5,
            "relation_growth_1h": 5,
            "relation_growth_24h": 5,
        }

    persist = AsyncMock()
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr(
        "graph_service.main.score_graph_risk_beta",
        AsyncMock(return_value={"risk_score": 90.0, "reasons": ["gnn"]}),
    )
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "u1"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk_score"] == 90.0
    assert body["relation_count"] == 5
    assert body["relation_growth_1h"] == 5
    assert body["relation_growth_24h"] == 5
    persist.assert_awaited()
    payload = persist.await_args.args[2]
    assert payload["risk_score"] == 90.0
    assert payload["relation_growth_1h"] == 5
    assert payload["relation_growth_24h"] == 5


def test_get_entity_risk_persist_failure_still_200(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    async def _compute(tenant_id, entity_id, checkpoint=None):
        return {
            "entity_id": entity_id,
            "risk_score": 20,
            "risk_factors": ["fast_growth_1h:5"],
            "connected_flagged_count": 0,
            "community_size": 1,
            "neighbor_device_count": 0,
            "scored": True,
            "relation_count": 5,
            "relation_growth_1h": 5,
            "relation_growth_24h": 5,
        }

    persist = AsyncMock(side_effect=RuntimeError("set failed"))
    monkeypatch.setattr("graph_service.main.compute_entity_risk", _compute)
    monkeypatch.setattr("graph_service.main.persist_entity_risk", persist)
    monkeypatch.setattr("graph_service.main.score_graph_risk_beta", AsyncMock(return_value=None))
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        r = client.get("/v1/analytics/entity-risk", params={"tenant_id": "t", "entity_id": "u1"})
    assert r.status_code == 200
    assert r.json()["scored"] is True
