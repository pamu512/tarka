"""HTTP integration: maker-checker requires distinct X-Actor-Id."""

from __future__ import annotations

import os

from case_api.main import app
from fastapi.testclient import TestClient


def _headers(actor: str) -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0], "X-Actor-Id": actor}


def test_maker_checker_http_same_actor_rejected_second_approves():
    with TestClient(app) as client:
        created = client.post(
            "/v1/cases",
            json={
                "tenant_id": "demo",
                "title": "MC case",
                "entity_id": "e-mc-1",
                "trace_id": "t-mc-1",
                "priority": "high",
            },
            headers=_headers("analyst-a"),
        )
        assert created.status_code in (200, 201), created.text
        case_id = created.json()["id"]

        parked = client.patch(
            f"/v1/cases/{case_id}",
            params={"tenant_id": "demo"},
            json={"status": "resolved", "disposition_reason_code": "CONFIRMED_FRAUD"},
            headers=_headers("analyst-a"),
        )
        assert parked.status_code == 200, parked.text
        body = parked.json()
        assert body.get("maker_checker", {}).get("pending") is True
        assert body["status"] != "resolved_fraud"
        assert any(str(x).startswith("mc_pending:") for x in (body.get("labels") or []))

        same = client.patch(
            f"/v1/cases/{case_id}",
            params={"tenant_id": "demo"},
            json={"maker_checker_approve": True},
            headers=_headers("analyst-a"),
        )
        assert same.status_code == 409, same.text
        detail = same.json().get("detail") or {}
        if isinstance(detail, dict):
            assert detail.get("reason_code") == "MAKER_CHECKER_REJECTED"

        ok = client.patch(
            f"/v1/cases/{case_id}",
            params={"tenant_id": "demo"},
            json={"maker_checker_approve": True},
            headers=_headers("analyst-b"),
        )
        assert ok.status_code == 200, ok.text
        approved = ok.json()
        assert approved["status"] == "resolved_fraud"
        assert approved.get("maker_checker", {}).get("pending") is False
