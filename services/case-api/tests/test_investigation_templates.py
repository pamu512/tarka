"""Marble #56: investigation template CRUD and case create with template UUID."""

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


def test_template_crud_and_create_case_with_uuid(case_client: TestClient) -> None:
    h = _api_headers()
    tid = "tenant-tmpl-1"
    create_body = {
        "tenant_id": tid,
        "slug": "high_touch",
        "name": "High touch review",
        "apply": {
            "status": "investigating",
            "priority": "high",
            "labels": ["tmpl_applied"],
            "assigned_team": "fraud-l1",
            "comment": "Template applied",
            "default_owner": "lead@example.com",
            "sla_hours": 2,
            "escalation_team": "fraud-l2",
        },
    }
    r = case_client.post("/v1/investigation-templates", json=create_body, headers=h)
    assert r.status_code == 201, r.text
    tpl = r.json()
    assert tpl["tenant_id"] == tid
    assert tpl["slug"] == "high_touch"
    assert tpl["apply_config"].get("escalation_team") == "fraud-l2"

    r2 = case_client.get(f"/v1/investigation-templates?tenant_id={tid}", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()["items"]) == 1

    tpl_id = tpl["id"]
    r3 = case_client.get(f"/v1/investigation-templates/{tpl_id}?tenant_id={tid}", headers=h)
    assert r3.status_code == 200
    assert r3.json()["name"] == "High touch review"

    r4 = case_client.patch(
        f"/v1/investigation-templates/{tpl_id}?tenant_id={tid}",
        json={"name": "High touch v2"},
        headers=h,
    )
    assert r4.status_code == 200
    assert r4.json()["name"] == "High touch v2"

    case_body = {
        "tenant_id": tid,
        "title": "Case from template",
        "entity_id": "ent-1",
        "trace_id": "trace-tmpl-1",
        "priority": "low",
        "playbook_id": tpl_id,
    }
    rc = case_client.post("/v1/cases", json=case_body, headers=h)
    assert rc.status_code == 201, rc.text
    c = rc.json()
    assert c["status"] == "investigating"
    assert c["priority"] == "high"
    assert "tmpl_applied" in c["labels"]
    assert "escalation_team:fraud-l2" in c["labels"]
    assert c["assigned_team"] == "fraud-l1"
    assert c["default_owner"] == "lead@example.com"
    assert c["sla_hours_override"] == 2
    assert c["applied_template_id"] == tpl_id

    rd = case_client.delete(f"/v1/investigation-templates/{tpl_id}?tenant_id={tid}", headers=h)
    assert rd.status_code == 204


def test_duplicate_template_slug_409(case_client: TestClient) -> None:
    h = _api_headers()
    tid = "tenant-dup"
    body = {
        "tenant_id": tid,
        "slug": "same_slug",
        "name": "One",
        "apply": {"priority": "high"},
    }
    assert case_client.post("/v1/investigation-templates", json=body, headers=h).status_code == 201
    r = case_client.post("/v1/investigation-templates", json=body, headers=h)
    assert r.status_code == 409


def test_create_case_unknown_template_uuid_422(case_client: TestClient) -> None:
    h = _api_headers()
    fake = "00000000-0000-4000-8000-000000000099"
    case_body = {
        "tenant_id": "t-x",
        "title": "x",
        "entity_id": "e",
        "trace_id": "t-422-tmpl",
        "priority": "low",
        "playbook_id": fake,
    }
    r = case_client.post("/v1/cases", json=case_body, headers=h)
    assert r.status_code == 422
