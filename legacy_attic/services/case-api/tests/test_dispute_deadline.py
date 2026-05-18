"""Refund Swatter #60: dispute deadline queue + idempotent external reprocess."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from case_api.dispute_deadline import alert_state, queue_item_view
from fastapi.testclient import TestClient


def _headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


def test_alert_state_near_and_breached():
    filed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    deadline = filed + timedelta(hours=10)
    assert (
        alert_state(
            deadline=deadline,
            reference_start=filed,
            now=filed + timedelta(hours=1),
            near_breach_ratio=0.2,
        )
        == "ok"
    )
    assert (
        alert_state(
            deadline=deadline,
            reference_start=filed,
            now=filed + timedelta(hours=9),
            near_breach_ratio=0.2,
        )
        == "near_breach"
    )
    assert (
        alert_state(
            deadline=deadline,
            reference_start=filed,
            now=deadline + timedelta(seconds=1),
            near_breach_ratio=0.2,
        )
        == "breached"
    )


def test_queue_item_view_hooks():
    class D:
        id = __import__("uuid").uuid4()
        tenant_id = "t1"
        status = "filed"
        dispute_type = "chargeback"
        filed_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        provider_response_deadline_at = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
        external_reprocess_count = 0
        last_external_reprocess_at = None

    now = datetime(2026, 1, 1, 0, 55, 0, tzinfo=UTC)
    v = queue_item_view(D(), now=now, near_breach_ratio=0.2)
    assert v["alert_state"] == "near_breach"
    assert "reprocess-external" in "".join(v["suggested_alert_hooks"])


@pytest.fixture
def dispute_client():
    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        with TestClient(app) as client:
            yield client


def test_reprocess_external_idempotent(dispute_client: TestClient) -> None:
    h = _headers()
    create = {
        "tenant_id": "acme-disp",
        "entity_id": "e1",
        "trace_id": "trace-reproc-1",
        "dispute_type": "chargeback",
        "amount": 10.0,
        "provider_response_deadline_hours": 48,
    }
    r = dispute_client.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    q = dispute_client.get(
        "/v1/disputes/ops/deadline-queue", params={"tenant_id": "acme-disp"}, headers=h
    )
    assert q.status_code == 200
    body = q.json()
    assert body["schema"] == "tarka.dispute_deadline_queue/v1"
    assert any(x["dispute_id"] == did for x in body["items"])

    key = "idem-reproc-1"
    p1 = dispute_client.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers={**h, "Idempotency-Key": key},
        json={"reason": "retry webhook"},
    )
    assert p1.status_code == 200, p1.text
    assert p1.json().get("idempotent_replay") is False
    p2 = dispute_client.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers={**h, "Idempotency-Key": key},
        json={"reason": "retry webhook"},
    )
    assert p2.status_code == 200
    assert p2.json().get("idempotent_replay") is True

    missing = dispute_client.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers=h,
        json={},
    )
    assert missing.status_code == 422
