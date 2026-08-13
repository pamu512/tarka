import inspect
from unittest.mock import AsyncMock

from graph_service.entity_risk_score import clamp_search_limit, search_hit_from_node
from graph_service import neo4j_client


def test_clamp_search_limit():
    assert clamp_search_limit(None) == 20
    assert clamp_search_limit(0) == 1
    assert clamp_search_limit(99) == 50
    assert clamp_search_limit(7) == 7


def test_search_hit_unscored_is_null_not_zero():
    hit = search_hit_from_node("t", "a", ["Account"], {})
    assert hit["scored"] is False
    assert hit["risk_score"] is None
    assert hit["labels"] == ["Account"]


def test_search_hit_scored_zero_is_zero():
    hit = search_hit_from_node(
        "t",
        "a",
        ["Person"],
        {"risk_computed_at": "2026-08-13T00:00:00Z", "risk_score": 0, "risk_factors": []},
    )
    assert hit["scored"] is True
    assert hit["risk_score"] == 0


def test_neo4j_search_cypher_is_parameterized_contains():
    src = inspect.getsource(neo4j_client.search_entities)
    assert "CONTAINS" in src
    assert "$q" in src
    assert "$tenant_id" in src
    assert "GraphRiskStats" in src
    assert "toLower" in src


def test_search_http_empty_q_no_store(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=[{"entity_id": "should_not_run"}])
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get("/v1/entities/search", params={"tenant_id": "t"}).json()
    assert data == {"entities": []}
    store.assert_not_called()


def test_search_http_passes_label_and_clamps(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=[
        {"entity_id": "fraud_frank", "tenant_id": "t", "labels": ["Person"], "scored": True, "risk_score": 72},
    ])
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app
    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "frank", "label": "Person", "limit": 999},
        ).json()
    assert data["entities"][0]["entity_id"] == "fraud_frank"
    store.assert_awaited_once()
    kwargs = store.await_args.kwargs
    assert kwargs["q"] == "frank"
    assert kwargs["label"] == "Person"
    assert kwargs["limit"] == 50


from graph_service import age_client, janusgraph_store


def test_janus_search_filters_in_python_not_full_graph_scan_without_tenant():
    src = inspect.getsource(janusgraph_store.search_entities)
    assert "tenant_id" in src
    assert "external_id" in src
    assert "GraphRiskStats" in src
    assert "search_hit_from_node" in src


def test_age_search_cypher_contains_and_tenant():
    src = inspect.getsource(age_client.search_entities)
    assert "CONTAINS" in src or "contains" in src
    assert "tenant_id" in src
    assert "GraphRiskStats" in src or "external_id" in src
