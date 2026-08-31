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
    from case_api.main import app

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        with TestClient(app) as client:
            yield client


def test_hold_keeps_entity_id_and_records_disposition(case_client: TestClient, monkeypatch):
    seen: list[dict] = []

    def _capture(**kwargs):
        seen.append(kwargs)

    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", _capture)
    r = case_client.post(
        "/v1/entities/buyer-demo/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=_api_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_id"] == "buyer-demo"
    assert body["outcome"] == "held"
    assert body["created_leftover"] is True
    assert seen and seen[0]["status"] == "held"
    assert seen[0]["case"].entity_id == "buyer-demo"

    again = case_client.post(
        "/v1/entities/buyer-demo/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=_api_headers(),
    )
    assert again.status_code == 200, again.text
    assert again.json()["entity_id"] == "buyer-demo"
    assert again.json()["created_leftover"] is False
    assert again.json()["case_id"] == body["case_id"]


def test_hold_works_without_api_key_on_insecure_desk(case_client: TestClient, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    r = case_client.post(
        "/v1/entities/hunt-eval-buyer/act",
        json={"tenant_id": "demo", "action": "hold"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["entity_id"] == "hunt-eval-buyer"
    assert r.json()["outcome"] == "held"


def test_hold_returns_200_when_audit_trail_missing(case_client: TestClient, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)

    async def _boom(*_a, **_k):
        raise SQLAlchemyError("audit_trail missing")

    monkeypatch.setattr("case_api.main._trail.record", _boom)
    r = case_client.post(
        "/v1/entities/buyer-trail-gap/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=_api_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["entity_id"] == "buyer-trail-gap"
    assert r.json()["outcome"] == "held"


def test_hold_rejects_blank_entity(case_client: TestClient):
    r = case_client.post(
        "/v1/entities/%20/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=_api_headers(),
    )
    assert r.status_code == 400
