"""POST /v1/ml/training-labels/by-trace maps disputes to fraud / not_fraud / unknown."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


@pytest.fixture
def ml_client():
    with (
        patch("case_api.main.evaluate_workflows", new_callable=AsyncMock),
        patch("case_api.dispute_api._send_ml_feedback", new_callable=AsyncMock),
    ):
        from case_api.main import app

        with TestClient(app) as client:
            yield client


def test_training_labels_prefers_latest_dispute_outcome(ml_client: TestClient) -> None:
    h = _headers()
    tid = "tenant-ml-1"
    tr = "trace-ml-label-1"
    create = {
        "tenant_id": tid,
        "entity_id": "ent1",
        "trace_id": tr,
        "dispute_type": "fraud_claim",
        "amount": 50.0,
        "provider_response_deadline_hours": 48,
    }
    r = ml_client.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    r2 = ml_client.patch(f"/v1/disputes/{did}", json={"outcome": "fraud_confirmed"}, headers=h)
    assert r2.status_code == 200, r2.text

    r3 = ml_client.post(
        "/v1/ml/training-labels/by-trace",
        json={"tenant_id": tid, "trace_ids": [tr, "missing-trace"]},
        headers=h,
    )
    assert r3.status_code == 200, r3.text
    body = r3.json()["labels"]
    assert body[tr]["case_management_label"] == "fraud"
    assert body[tr]["case_label_source"] == "dispute"
    assert body[tr]["dispute_outcome"] == "fraud_confirmed"
    assert body["missing-trace"]["case_management_label"] == "unknown"
    assert body["missing-trace"]["case_label_source"] == "none"
