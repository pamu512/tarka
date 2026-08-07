"""Multi-party collusion links: role mapper + graph risk_propagation join."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from case_api.workflow import WorkflowContext
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


def test_map_labels_courier_and_seller():
    from case_api.multi_party_links import map_labels_to_roles

    assert "courier" in map_labels_to_roles(["Driver", "Device"])
    assert map_labels_to_roles(["Widget"]) == ["unknown"]


@pytest.fixture
def links_client(monkeypatch):
    monkeypatch.setenv("GRAPH_SERVICE_URL", "http://graph.test")
    monkeypatch.setattr(
        "case_api.multi_party_links.settings.graph_service_url",
        "http://graph.test",
    )
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        from case_api.main import app

        with TestClient(app) as client:

            async def fake_get(url, **kwargs):
                u = str(url)

                class Resp:
                    status_code = 200

                    def raise_for_status(self):
                        return None

                    def json(self):
                        if "/v1/analytics/risk-propagation" in u:
                            return {
                                "entities": [
                                    {
                                        "entity_id": "neighbor-1",
                                        "entity_labels": ["Courier"],
                                        "propagated_risk_score": 50.0,
                                        "distance": 1,
                                        "path_description": "(anchor)-[SHARED_DEVICE]->(neighbor-1)",
                                        "rel_types": ["SHARED_DEVICE"],
                                    }
                                ]
                            }
                        return {}

                return Resp()

            client.app.state.http.get = AsyncMock(side_effect=fake_get)
            yield client


def test_multi_party_links_joins_cases(links_client: TestClient):
    tenant = "t-collusion"
    anchor = links_client.post(
        "/v1/cases",
        json={
            "tenant_id": tenant,
            "title": "Anchor",
            "entity_id": "anchor-ent",
            "trace_id": "trace-anchor",
        },
        headers=_api_headers(),
    )
    assert anchor.status_code == 201, anchor.text
    anchor_id = anchor.json()["id"]

    neighbor = links_client.post(
        "/v1/cases",
        json={
            "tenant_id": tenant,
            "title": "Neighbor case",
            "entity_id": "neighbor-1",
            "trace_id": "trace-neighbor",
            "priority": "high",
        },
        headers=_api_headers(),
    )
    assert neighbor.status_code == 201, neighbor.text

    r = links_client.get(
        f"/v1/cases/{anchor_id}/multi-party-links",
        params={"tenant_id": tenant, "depth": 3},
        headers=_api_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_id"] == "anchor-ent"
    assert body["links"]
    assert body["links"][0]["roles"] == ["courier"]
    assert any(c["case_id"] for c in body["links"][0]["cases"])
    assert body["links"][0]["shared_signals"] == ["shared_device"]


def test_list_cases_filters_by_entity_id(links_client: TestClient):
    tenant = "t-filter"
    links_client.post(
        "/v1/cases",
        json={
            "tenant_id": tenant,
            "title": "Match",
            "entity_id": "ent-filter-me",
            "trace_id": "trace-1",
        },
        headers=_api_headers(),
    )
    links_client.post(
        "/v1/cases",
        json={
            "tenant_id": tenant,
            "title": "Other",
            "entity_id": "ent-other",
            "trace_id": "trace-2",
        },
        headers=_api_headers(),
    )
    r = links_client.get(
        "/v1/cases",
        params={"tenant_id": tenant, "entity_id": "ent-filter-me"},
        headers=_api_headers(),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["entity_id"] == "ent-filter-me"


def test_multi_party_links_degraded_on_graph_failure(monkeypatch):
    monkeypatch.setattr(
        "case_api.multi_party_links.settings.graph_service_url",
        "http://graph.test",
    )
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        from case_api.main import app

        with TestClient(app) as client:
            client.app.state.http.get = AsyncMock(side_effect=ConnectionError("down"))
            created = client.post(
                "/v1/cases",
                json={
                    "tenant_id": "t-degraded",
                    "title": "Anchor",
                    "entity_id": "ent-degraded",
                    "trace_id": "trace-degraded",
                },
                headers=_api_headers(),
            )
            assert created.status_code == 201
            cid = created.json()["id"]
            r = client.get(
                f"/v1/cases/{cid}/multi-party-links",
                params={"tenant_id": "t-degraded"},
                headers=_api_headers(),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["links"] == []
            assert body["degraded"] is True
            assert body["degraded_reason"] == "graph_unavailable"
