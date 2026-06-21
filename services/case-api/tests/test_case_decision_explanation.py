"""xFraud #69: case API surfaces graph decision explanation via decision-api audit."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from case_api.workflow import WorkflowContext
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


@pytest.fixture
def client_with_http_mock():
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        from case_api.main import app

        with TestClient(app) as client:

            async def fake_get(url, **kwargs):
                u = str(url)

                class Resp:
                    status_code = 200

                    def json(self):
                        if "/v1/audit/" in u:
                            return {
                                "decision": "review",
                                "score": 71.0,
                                "graph_decision_explanation": {
                                    "schema_id": "tarka.graph_decision_explanation/v1",
                                    "trace_id": "trace-xf-1",
                                    "why_links": [{"factor_id": "f1", "evidence": []}],
                                },
                            }
                        return {}

                return Resp()

            client.app.state.http.get = AsyncMock(side_effect=fake_get)
            yield client


def test_case_decision_explanation_chain(client_with_http_mock: TestClient) -> None:
    body = {
        "tenant_id": "acme",
        "title": "Graph case",
        "entity_id": "ent-1",
        "trace_id": "trace-xf-1",
        "priority": "low",
    }
    r = client_with_http_mock.post("/v1/cases", json=body, headers=_api_headers())
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r2 = client_with_http_mock.get(
        f"/v1/cases/{cid}/decision-explanation",
        params={"tenant_id": "acme"},
        headers=_api_headers(),
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["source"] == "decision_audit"
    assert data["graph_decision_explanation"]["schema_id"] == "tarka.graph_decision_explanation/v1"
    assert data["decision"] == "review"
