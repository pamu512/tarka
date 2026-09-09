"""G4.3: inbound product ACK bound to trace_id + action_id. Not Promote/Demote."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.enforcement import (
    append_enforcement_journal,
    idempotent_action_id,
)

_REPO = Path(__file__).resolve().parents[3]
_CONTRACT = _REPO / "docs" / "contracts" / "enforcement-v1.md"
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"


def _action_id(trace_id: str, tenant_id: str = "t1", action: str = "deny") -> str:
    return idempotent_action_id(
        tenant_id=tenant_id, trace_id=trace_id, action=action, pack_hash=""
    )


def _seed_known_trace(trace_id: str, tenant_id: str = "t1") -> None:
    append_enforcement_journal(
        {
            "schema_id": "tarka.enforcement_delivery/v1",
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "status": "acked",
        }
    )


def _ack_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TARKA_PRODUCT_ACK_PATH", str(tmp_path / "product_acks.jsonl"))
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", raising=False)


def _app():
    from decision_api.product_ack import router

    app = FastAPI()
    app.include_router(router)
    return app


async def _client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def test_ack_schema_fields() -> None:
    from decision_api.product_ack import ACK_FIELDS, ACK_SCHEMA

    assert ACK_SCHEMA == "tarka.product_ack/v1"
    assert ACK_FIELDS == ("trace_id", "action_id", "status", "ts", "actor")


@pytest.mark.asyncio
async def test_ack_known_trace_queryable_by_trace_and_action_id(
    monkeypatch, tmp_path
) -> None:
    _ack_env(monkeypatch, tmp_path)
    trace_id = "tr-known"
    action_id = _action_id(trace_id)
    _seed_known_trace(trace_id)
    body = {
        "trace_id": trace_id,
        "action_id": action_id,
        "status": "applied",
        "ts": "2026-09-09T04:00:00Z",
        "actor": "t1",
    }
    async for client in _client(_app()):
        posted = await client.post("/v1/enforcement/acks", json=body)
        assert posted.status_code == 200
        stored = posted.json()
        for key in ("trace_id", "action_id", "status", "ts", "actor"):
            assert stored[key] == body[key]
        assert stored["schema_id"] == "tarka.product_ack/v1"

        by_trace = await client.get(
            "/v1/enforcement/acks",
            params={"trace_id": trace_id, "tenant_id": "t1"},
        )
        assert by_trace.status_code == 200
        items = by_trace.json()["items"]
        assert items
        assert items[-1]["status"] == "applied"
        assert items[-1]["trace_id"] == trace_id
        assert items[-1]["action_id"] == action_id

        by_action = await client.get(
            "/v1/enforcement/acks",
            params={
                "trace_id": trace_id,
                "action_id": action_id,
                "tenant_id": "t1",
            },
        )
        assert by_action.status_code == 200
        assert by_action.json()["items"][-1]["action_id"] == action_id


@pytest.mark.asyncio
async def test_unknown_trace_is_structured_error_not_silent_200(
    monkeypatch, tmp_path
) -> None:
    _ack_env(monkeypatch, tmp_path)
    body = {
        "trace_id": "tr-missing",
        "action_id": _action_id("tr-missing"),
        "status": "received",
        "ts": "2026-09-09T04:00:00Z",
        "actor": "t1",
    }
    async for client in _client(_app()):
        r = await client.post("/v1/enforcement/acks", json=body)
        assert r.status_code == 404
        detail = r.json()["detail"]
        assert detail["error"] == "unknown_trace"
        assert detail["trace_id"] == "tr-missing"
        listed = await client.get(
            "/v1/enforcement/acks",
            params={"trace_id": "tr-missing", "tenant_id": "t1"},
        )
        assert listed.status_code == 200
        assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_malformed_action_id_is_structured_error(monkeypatch, tmp_path) -> None:
    _ack_env(monkeypatch, tmp_path)
    _seed_known_trace("tr-known")
    async for client in _client(_app()):
        for bad in ("", "not-an-id", "abc", "g" * 64, "a" * 63):
            r = await client.post(
                "/v1/enforcement/acks",
                json={
                    "trace_id": "tr-known",
                    "action_id": bad,
                    "status": "received",
                    "ts": "2026-09-09T04:00:00Z",
                    "actor": "t1",
                },
            )
            assert r.status_code == 400, bad
            detail = r.json()["detail"]
            assert detail["error"] == "malformed_action_id"
            assert "action_id" in detail


@pytest.mark.asyncio
async def test_ack_does_not_call_promote_confirm_demote_or_change_pack(
    monkeypatch, tmp_path
) -> None:
    _ack_env(monkeypatch, tmp_path)
    pack = {"mode": "active", "lifecycle": {}, "rules": []}
    pack_path = tmp_path / "live_pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    before = pack_path.read_text(encoding="utf-8")
    calls: list[str] = []

    def _boom(name: str):
        def _inner(*_a, **_k):
            calls.append(name)
            raise AssertionError(f"{name} must not run on product ACK")

        return _inner

    import decision_api.l2_draft as l2

    monkeypatch.setattr(l2, "propose_demote", _boom("propose_demote"))
    monkeypatch.setattr(l2, "confirm_demote", _boom("confirm_demote"))

    _seed_known_trace("tr-known")
    from decision_api.product_ack import accept_product_ack

    accept_product_ack(
        {
            "trace_id": "tr-known",
            "action_id": _action_id("tr-known"),
            "status": "applied",
            "ts": "2026-09-09T04:00:00Z",
            "actor": "t1",
        }
    )
    assert calls == []
    assert pack_path.read_text(encoding="utf-8") == before

    src = (
        Path(__file__).resolve().parents[1] / "src" / "decision_api" / "product_ack.py"
    ).read_text(encoding="utf-8")
    lowered = src.lower()
    assert "propose_demote" not in src
    assert "confirm_demote" not in src
    assert "promote_shadow" not in src
    assert "promote_vertical" not in src
    assert "auto-demote" not in lowered
    assert "case crm" not in lowered
    assert "case inbox" not in lowered


@pytest.mark.asyncio
async def test_ack_rejects_bad_signature_when_secret_set(monkeypatch, tmp_path) -> None:
    _ack_env(monkeypatch, tmp_path)
    secret = "g43-ack-secret"
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", secret)
    _seed_known_trace("tr-known")
    payload = {
        "trace_id": "tr-known",
        "action_id": _action_id("tr-known"),
        "status": "received",
        "ts": "2026-09-09T04:00:00Z",
        "actor": "t1",
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    async for client in _client(_app()):
        unsigned = await client.post(
            "/v1/enforcement/acks",
            content=raw,
            headers={"content-type": "application/json"},
        )
        assert unsigned.status_code == 401
        assert unsigned.json()["detail"]["error"] == "bad_signature"

        sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        signed = await client.post(
            "/v1/enforcement/acks",
            content=raw,
            headers={
                "content-type": "application/json",
                "x-tarka-signature": sig,
            },
        )
        assert signed.status_code == 200
        assert signed.json()["status"] == "received"


def test_contract_and_claim_lock_ack_both_sides() -> None:
    contract = _CONTRACT.read_text(encoding="utf-8").lower()
    claim = _CLAIM.read_text(encoding="utf-8").lower()
    for text in (contract, claim):
        assert "product ack" in text or "product_ack" in text
        assert "trace_id" in text
        assert "action_id" in text
        assert "promote" in text or "demote" in text
        assert "case crm" in text
    assert "/v1/enforcement/acks" in _CONTRACT.read_text(encoding="utf-8")
    assert "desk" in contract
    assert "g4.4" in contract
    assert (
        "not promote" in claim
        or "not a promote" in claim
        or "ack is not promote" in claim
    )
