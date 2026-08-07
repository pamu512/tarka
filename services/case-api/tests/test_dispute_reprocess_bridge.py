"""Dispute reprocess → decision-api evaluate bridge (fail-soft)."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from case_api.dispute_reprocess_bridge import (
    build_dispute_evaluate_body,
    run_dispute_reprocess_evaluate,
)
from fastapi.testclient import TestClient


def _headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


def _dispute_row(**overrides):
    base = {
        "id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "acme-disp",
        "entity_id": "e1",
        "trace_id": "trace-reproc-eval",
        "dispute_type": "chargeback",
        "reason_code": "4853",
        "amount": 42.0,
        "currency": "USD",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_dispute_evaluate_body_includes_checkpoint_and_subtype():
    row = _dispute_row()
    body = build_dispute_evaluate_body(
        row,
        reason="retry webhook",
        original_audit={
            "metadata": {
                "delivery_confirmation_hash": "abc",
                "expected_delivery_hash": "def",
                "dispute_hours_since_delivery": 12,
            }
        },
    )
    assert body["event_type"] == "custom"
    assert body["metadata"]["checkpoint"] == "dispute"
    assert body["metadata"]["event_subtype"] == "chargeback"
    assert body["metadata"]["dispute_id"] == str(row.id)
    assert body["metadata"]["reason_code"] == "4853"
    assert body["metadata"]["delivery_confirmation_hash"] == "abc"
    assert body["metadata"]["dispute_hours_since_delivery"] == 12


@pytest.mark.asyncio
async def test_run_dispute_reprocess_evaluate_ok():
    row = _dispute_row()

    class Resp:
        status_code = 200

        def json(self):
            return {
                "decision": "review",
                "score": 88.0,
                "tags": ["risk:refund_burst", "vertical:marketplace"],
                "rule_hits": ["friendly_fraud_window"],
                "decision_status": "Healthy",
            }

    http = AsyncMock()
    http.post = AsyncMock(return_value=Resp())
    http.get = AsyncMock()

    out = await run_dispute_reprocess_evaluate(
        http,
        decision_api_url="http://decision.test",
        api_key="secret",
        dispute_row=row,
        reason="retry",
        original_audit={},
    )
    assert out["ok"] is True
    assert out["decision"] == "review"
    assert out["tags"] == ["risk:refund_burst", "vertical:marketplace"]
    assert out.get("is_friendly_fraud_risk") is True
    http.post.assert_awaited_once()
    call = http.post.await_args
    assert call.args[0] == "http://decision.test/v1/decisions/evaluate"
    assert call.kwargs["headers"]["x-api-key"] == "secret"


@pytest.mark.asyncio
async def test_run_dispute_reprocess_evaluate_fail_soft_on_exception():
    http = AsyncMock()
    http.post = AsyncMock(side_effect=ConnectionError("decision-api down"))
    http.get = AsyncMock()

    out = await run_dispute_reprocess_evaluate(
        http,
        decision_api_url="http://decision.test",
        api_key="",
        dispute_row=_dispute_row(),
        reason=None,
        original_audit={},
    )
    assert out == {"ok": False, "degraded": True, "error": "decision-api down"}


@pytest.fixture
def dispute_client_with_evaluate():
    import case_api.main  # noqa: F401

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        with TestClient(app) as client:

            async def fake_post(url, **kwargs):
                u = str(url)

                class Resp:
                    status_code = 200

                    def json(self):
                        if "/v1/decisions/evaluate" in u:
                            return {
                                "decision": "review",
                                "score": 77.0,
                                "tags": ["risk:refund_burst"],
                                "decision_status": "Healthy",
                            }
                        return {}

                return Resp()

            client.app.state.http.post = AsyncMock(side_effect=fake_post)
            client.app.state.http.get = AsyncMock(
                return_value=SimpleNamespace(status_code=404, json=lambda: {})
            )
            yield client


def test_reprocess_external_includes_decision_reprocess_ok(
    dispute_client_with_evaluate: TestClient,
) -> None:
    h = _headers()
    create = {
        "tenant_id": "acme-disp",
        "entity_id": "e-eval",
        "trace_id": "trace-eval-1",
        "dispute_type": "chargeback",
        "amount": 10.0,
        "provider_response_deadline_hours": 48,
    }
    r = dispute_client_with_evaluate.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    p = dispute_client_with_evaluate.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers={**h, "Idempotency-Key": "idem-eval-1"},
        json={"reason": "evaluate friendly fraud"},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    dr = body.get("decision_reprocess") or {}
    assert dr.get("ok") is True
    assert dr.get("decision") == "review"
    assert "risk:refund_burst" in (dr.get("tags") or [])


@pytest.fixture
def dispute_client_evaluate_raises():
    import case_api.main  # noqa: F401

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock):
        from case_api.main import app

        with TestClient(app) as client:
            client.app.state.http.post = AsyncMock(side_effect=RuntimeError("evaluate boom"))
            client.app.state.http.get = AsyncMock(
                return_value=SimpleNamespace(status_code=404, json=lambda: {})
            )
            yield client


def test_get_dispute_includes_latest_decision_reprocess(
    dispute_client_with_evaluate: TestClient,
) -> None:
    h = _headers()
    create = {
        "tenant_id": "acme-disp",
        "entity_id": "e-get-reproc",
        "trace_id": "trace-get-reproc",
        "dispute_type": "chargeback",
        "amount": 15.0,
    }
    r = dispute_client_with_evaluate.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    before = dispute_client_with_evaluate.get(f"/v1/disputes/{did}", headers=h)
    assert before.status_code == 200, before.text
    assert before.json().get("latest_decision_reprocess") is None
    assert before.json().get("is_friendly_fraud_risk") is None

    p = dispute_client_with_evaluate.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers={**h, "Idempotency-Key": "idem-get-reproc"},
        json={"reason": "surface on detail"},
    )
    assert p.status_code == 200, p.text

    got = dispute_client_with_evaluate.get(f"/v1/disputes/{did}", headers=h)
    assert got.status_code == 200, got.text
    body = got.json()
    dr = body.get("latest_decision_reprocess") or {}
    assert dr.get("ok") is True
    assert dr.get("decision") == "review"
    assert dr.get("score") == 77.0
    assert "risk:refund_burst" in (dr.get("tags") or [])
    assert body.get("is_friendly_fraud_risk") is True


def test_reprocess_external_evaluate_error_still_200(
    dispute_client_evaluate_raises: TestClient,
) -> None:
    h = _headers()
    create = {
        "tenant_id": "acme-disp",
        "entity_id": "e-eval-fail",
        "trace_id": "trace-eval-fail",
        "dispute_type": "dispute",
        "amount": 5.0,
    }
    r = dispute_client_evaluate_raises.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    p = dispute_client_evaluate_raises.post(
        f"/v1/disputes/{did}/reprocess-external?tenant_id=acme-disp",
        headers={**h, "Idempotency-Key": "idem-eval-fail"},
        json={"reason": "should not fail HTTP"},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body.get("ok") is True
    dr = body.get("decision_reprocess") or {}
    assert dr.get("ok") is False
    assert dr.get("degraded") is True
    assert "evaluate boom" in str(dr.get("error", ""))
