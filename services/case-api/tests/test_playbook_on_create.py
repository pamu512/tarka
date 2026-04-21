"""Marble #56 slice: optional playbook_id on POST /v1/cases."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from case_api.workflow import WorkflowContext
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys, "tests/conftest.py should set API_KEYS"
    return {"X-API-Key": keys[0]}


@pytest.fixture
def case_client():
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        from case_api.main import app

        with TestClient(app) as client:
            yield client


def test_create_case_with_playbook_id_applies_template(case_client: TestClient) -> None:
    body = {
        "tenant_id": "acme",
        "title": "Suspicious ATO",
        "entity_id": "user-99",
        "trace_id": "trace-pb-1",
        "priority": "medium",
        "playbook_id": "escalate_fraud",
    }
    r = case_client.post("/v1/cases", json=body, headers=_api_headers())
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["tenant_id"] == "acme"
    assert data["status"] == "investigating"
    assert data["priority"] == "critical"
    assert "fraud_watch" in data["labels"]
    assert data["assigned_team"] == "fraud-l2"


def test_create_case_unknown_playbook_returns_422(case_client: TestClient) -> None:
    body = {
        "tenant_id": "acme",
        "title": "x",
        "entity_id": "e",
        "trace_id": "t-422",
        "priority": "low",
        "playbook_id": "not_a_real_playbook",
    }
    r = case_client.post("/v1/cases", json=body, headers=_api_headers())
    assert r.status_code == 422
    assert "unknown playbook_id" in (r.json().get("detail") or "").lower()
