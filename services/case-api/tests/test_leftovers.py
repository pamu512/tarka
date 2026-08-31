import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from case_api.leftover import is_leftover, leftover_origin
from case_api.workflow import WorkflowContext
from fastapi.testclient import TestClient
from sqlalchemy import delete


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys, "tests/conftest.py should set API_KEYS"
    return {"X-API-Key": keys[0]}


@pytest.fixture
def case_client():
    from case_api.db import SessionLocal
    from case_api.main import app
    from case_api.models import Case, LeftoverPromoteAck

    async def _wipe_leftover_state():
        # ponytail: :memory: SQLite is process-wide; GET promote-ack is tenant-wide
        async with SessionLocal() as session:
            await session.execute(delete(LeftoverPromoteAck))
            await session.execute(delete(Case))
            await session.commit()

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        with TestClient(app) as client:
            asyncio.run(_wipe_leftover_state())
            yield client


def _case(**kw):
    base = {"status": "open", "entity_id": "buyer-1", "labels": ["act:hold"]}
    base.update(kw)
    return SimpleNamespace(**base)


def test_leftover_hold_open():
    assert is_leftover(_case()) is True
    assert leftover_origin(["act:hold"]) == "hold"


def test_leftover_evaluate_open():
    assert is_leftover(_case(labels=["origin:evaluate"])) is True
    assert leftover_origin(["origin:evaluate"]) == "evaluate"


def test_leftover_both():
    assert leftover_origin(["act:hold", "origin:evaluate"]) == "both"


def test_not_leftover_blank_entity_or_allow_case_or_closed():
    assert is_leftover(_case(entity_id="")) is False
    assert is_leftover(_case(entity_id="  ")) is False
    assert is_leftover(_case(labels=[])) is False
    assert is_leftover(_case(status="resolved", labels=["act:hold"])) is False
    assert is_leftover(_case(status="closed", labels=["origin:evaluate"])) is False


def test_evaluate_mint_is_leftover_flag_and_blank_are_not(case_client):
    ev = case_client.post(
        "/v1/cases",
        json={
            "tenant_id": "demo",
            "title": "Auto: deny payment e1",
            "entity_id": "e1",
            "trace_id": "tr-1",
            "labels": ["origin:evaluate"],
            "last_outcome": "deny",
        },
        headers=_api_headers(),
    )
    assert ev.status_code == 201, ev.text
    plain = case_client.post(
        "/v1/cases",
        json={
            "tenant_id": "demo",
            "title": "manual",
            "entity_id": "e2",
            "trace_id": "tr-2",
        },
        headers=_api_headers(),
    )
    assert plain.status_code == 201, plain.text
    rows = case_client.get("/v1/leftovers", params={"tenant_id": "demo"}, headers=_api_headers())
    assert rows.status_code == 200, rows.text
    body = rows.json()
    ids = {r["entity_id"] for r in body["leftovers"]}
    assert "e1" in ids
    assert "e2" not in ids
    e1 = next(r for r in body["leftovers"] if r["entity_id"] == "e1")
    assert e1["origin"] == "evaluate"
    assert e1["last_outcome"] == "deny"


def test_claim_same_actor_noop_other_actor_409(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    a = {**_api_headers(), "X-Actor-Id": "ana-a"}
    b = {**_api_headers(), "X-Actor-Id": "ana-b"}
    hold = case_client.post(
        "/v1/entities/buyer-a/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=a,
    )
    assert hold.status_code == 200, hold.text
    cid = hold.json()["case_id"]
    again = case_client.post(f"/v1/leftovers/{cid}/claim", params={"tenant_id": "demo"}, headers=a)
    assert again.status_code == 200, again.text
    stolen = case_client.post(f"/v1/leftovers/{cid}/claim", params={"tenant_id": "demo"}, headers=b)
    assert stolen.status_code == 409
    detail = stolen.json()
    assert detail["detail"] == "claimed"
    assert detail["claimed_by"] == "ana-a"


def test_hold_does_not_steal(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    case_client.post(
        "/v1/entities/buyer-b/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers={**_api_headers(), "X-Actor-Id": "ana-a"},
    )
    r = case_client.post(
        "/v1/entities/buyer-b/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers={**_api_headers(), "X-Actor-Id": "ana-b"},
    )
    assert r.status_code == 409
    assert r.json()["claimed_by"] == "ana-a"


def test_resolve_requires_known_reason_and_closes(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    monkeypatch.setattr("case_api.main._persist_disposition_y_label", lambda *a, **k: None)
    case_client.post(
        "/v1/entities/buyer-c/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=_api_headers(),
    )
    bad = case_client.post(
        "/v1/entities/buyer-c/act",
        json={"tenant_id": "demo", "action": "resolve"},
        headers=_api_headers(),
    )
    assert bad.status_code == 400
    ok = case_client.post(
        "/v1/entities/buyer-c/act",
        json={"tenant_id": "demo", "action": "resolve", "reason_code": "FALSE_POSITIVE"},
        headers=_api_headers(),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["outcome"] == "resolved"
    listed = case_client.get("/v1/leftovers", params={"tenant_id": "demo"}, headers=_api_headers())
    assert listed.status_code == 200, listed.text
    assert "buyer-c" not in {r["entity_id"] for r in listed.json()["leftovers"]}


def test_release_clears_claim_stays_leftover(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    h = {**_api_headers(), "X-Actor-Id": "ana-a"}
    case_client.post(
        "/v1/entities/buyer-d/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=h,
    )
    r = case_client.post(
        "/v1/entities/buyer-d/act",
        json={"tenant_id": "demo", "action": "release"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    rows = case_client.get(
        "/v1/leftovers",
        params={"tenant_id": "demo", "free_only": 1},
        headers=_api_headers(),
    )
    assert rows.status_code == 200, rows.text
    d = next(x for x in rows.json()["leftovers"] if x["entity_id"] == "buyer-d")
    assert d["claimed_by"] is None
    assert d["last_act"] == "released"


def test_promote_ack_403_unless_claimer_and_stale_after_release(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    a = {**_api_headers(), "X-Actor-Id": "ana-a"}
    b = {**_api_headers(), "X-Actor-Id": "ana-b"}
    case_client.post(
        "/v1/entities/buyer-ack/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=a,
    )
    denied = case_client.post(
        "/v1/leftovers/promote-ack",
        json={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=b,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "not_a_claimer"
    ok = case_client.post(
        "/v1/leftovers/promote-ack",
        json={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=a,
    )
    assert ok.status_code == 200, ok.text
    got = case_client.get(
        "/v1/leftovers/promote-ack",
        params={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=_api_headers(),
    )
    assert got.status_code == 200
    body = got.json()
    assert body["required"] is True
    assert body["ack"]["acked_by"] == "ana-a"
    case_client.post(
        "/v1/entities/buyer-ack/act",
        json={"tenant_id": "demo", "action": "release"},
        headers=a,
    )
    after = case_client.get(
        "/v1/leftovers/promote-ack",
        params={"tenant_id": "demo", "draft_id": "scout_x"},
        headers=_api_headers(),
    )
    assert after.json()["required"] is False


def test_promote_ack_blank_draft_id_400(case_client, monkeypatch):
    monkeypatch.setattr("case_api.main._maybe_record_human_disposition_decision", lambda **_k: None)
    a = {**_api_headers(), "X-Actor-Id": "ana-a"}
    case_client.post(
        "/v1/entities/buyer-ack/act",
        json={"tenant_id": "demo", "action": "hold"},
        headers=a,
    )
    blank = case_client.post(
        "/v1/leftovers/promote-ack",
        json={"tenant_id": "demo", "draft_id": "  "},
        headers=a,
    )
    assert blank.status_code == 400
