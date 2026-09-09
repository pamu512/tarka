"""D9.3: tenant-scoped journal query. Not a case CRM. Not Promote/Demote."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.enforcement import (
    append_enforcement_journal,
    apply_enforcement_adapters,
    idempotent_action_id,
    logical_enforcement_delivery,
)

_REPO = Path(__file__).resolve().parents[3]
_CONTRACT = _REPO / "docs" / "contracts" / "enforcement-v1.md"
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"


def _action_id(trace_id: str, tenant_id: str = "t1", action: str = "deny") -> str:
    return idempotent_action_id(
        tenant_id=tenant_id, trace_id=trace_id, action=action, pack_hash=""
    )


def _journal_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )
    monkeypatch.setenv("TARKA_PRODUCT_ACK_PATH", str(tmp_path / "product_acks.jsonl"))
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)


def _seed(
    *,
    trace_id: str,
    tenant_id: str,
    status: str,
    action: str = "deny",
    attempt_count: int | None = None,
    reason: str | None = None,
    error: str | None = None,
    last_error: str | None = None,
    ts: str = "2026-09-09T04:00:00Z",
) -> str:
    aid = _action_id(trace_id, tenant_id, action)
    row: dict = {
        "schema_id": "tarka.enforcement_delivery/v1",
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "action_id": aid,
        "idempotency_key": aid,
        "status": status,
        "ts": ts,
    }
    if attempt_count is not None:
        row["attempt_count"] = attempt_count
    if reason is not None:
        row["reason"] = reason
    if error is not None:
        row["error"] = error
    if last_error is not None:
        row["last_error"] = last_error
    append_enforcement_journal(row)
    return aid


def _app():
    from decision_api.product_ack import router

    app = FastAPI()
    app.include_router(router)
    return app


async def _client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _zero_wait(_attempt: int) -> None:
    return None


def _row(body: dict, action_id: str | None = None) -> dict:
    rows = body["deliveries"]
    if action_id is None:
        assert rows
        return rows[0]
    matched = [r for r in rows if r["action_id"] == action_id]
    assert matched
    return matched[0]


@pytest.mark.asyncio
async def test_known_trace_returns_logical_delivery_schema(
    monkeypatch, tmp_path
) -> None:
    _journal_env(monkeypatch, tmp_path)
    aid = _seed(
        trace_id="tr-known",
        tenant_id="t1",
        status="acked",
        attempt_count=2,
        ts="2026-09-09T05:00:00Z",
    )
    logical = logical_enforcement_delivery(aid)
    assert logical is not None
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-known", "tenant_id": "t1"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["schema_id"] == "tarka.enforcement_delivery_query/v1"
        assert "deliveries" in body
        row = _row(body, aid)
        assert row["action_id"] == aid
        assert row["trace_id"] == "tr-known"
        assert row["tenant_id"] == "t1"
        assert row["attempt_count"] == logical["attempt_count"] == 2
        assert "last_status" in row
        assert "last_error" in row
        assert "acked_at" in row
        assert "assignee" not in row
        assert "sar" not in row
        assert "ticket" not in row


@pytest.mark.asyncio
async def test_unknown_trace_is_empty_deliveries_not_500(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    _seed(trace_id="tr-other", tenant_id="t1", status="acked")
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-missing", "tenant_id": "t1"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["deliveries"] == []
        assert body.get("error") != "internal"


@pytest.mark.asyncio
async def test_tenant_a_cannot_see_tenant_b(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    aid_a = _seed(trace_id="tr-shared", tenant_id="tenant-a", status="acked")
    aid_b = _seed(trace_id="tr-shared", tenant_id="tenant-b", status="dead_lettered")
    async for client in _client(_app()):
        a = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-shared", "tenant_id": "tenant-a"},
        )
        b = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-shared", "tenant_id": "tenant-b"},
        )
        assert a.status_code == 200
        assert b.status_code == 200
        ids_a = {row["action_id"] for row in a.json()["deliveries"]}
        ids_b = {row["action_id"] for row in b.json()["deliveries"]}
        assert ids_a == {aid_a}
        assert ids_b == {aid_b}
        assert aid_b not in ids_a
        assert aid_a not in ids_b
        assert all(row["tenant_id"] == "tenant-a" for row in a.json()["deliveries"])
        assert all(row["tenant_id"] == "tenant-b" for row in b.json()["deliveries"])


@pytest.mark.asyncio
async def test_empty_webhook_url_maps_to_not_configured(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_URL", raising=False)

    class _Http:
        async def post(self, *_a, **_k):
            raise AssertionError("empty URL must not POST")

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-off",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert out["journal"]["status"] == "skipped"
    aid = out["action_id"]
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-off", "tenant_id": "t1", "action_id": aid},
        )
        assert r.status_code == 200
        row = _row(r.json(), aid)
        assert row["last_status"] == "not_configured"
        assert row["acked_at"] is None


@pytest.mark.asyncio
async def test_journal_http_2xx_is_emitted_not_product_ack(
    monkeypatch, tmp_path
) -> None:
    _journal_env(monkeypatch, tmp_path)
    aid = _seed(
        trace_id="tr-2xx",
        tenant_id="t1",
        status="acked",
        ts="2026-09-09T06:11:00Z",
    )
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-2xx", "tenant_id": "t1"},
        )
        row = _row(r.json(), aid)
        assert row["last_status"] == "emitted"
        assert row["acked_at"] == "2026-09-09T06:11:00Z"


@pytest.mark.asyncio
async def test_product_ack_sets_last_status_acked(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    aid = _seed(
        trace_id="tr-ack",
        tenant_id="t1",
        status="acked",
        ts="2026-09-09T06:00:00Z",
    )
    from decision_api.product_ack import accept_product_ack

    accept_product_ack(
        {
            "trace_id": "tr-ack",
            "action_id": aid,
            "status": "applied",
            "ts": "2026-09-09T06:30:00Z",
            "actor": "t1",
        }
    )
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-ack", "tenant_id": "t1", "action_id": aid},
        )
        row = _row(r.json(), aid)
        assert row["last_status"] == "acked"
        assert row["acked_at"] == "2026-09-09T06:30:00Z"


@pytest.mark.asyncio
async def test_filter_by_action_id_and_status(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    deny = _seed(
        trace_id="tr-filt",
        tenant_id="t1",
        status="retrying",
        action="deny",
        attempt_count=2,
        error="timeout",
    )
    _seed(
        trace_id="tr-filt",
        tenant_id="t1",
        status="skipped",
        action="review",
        reason="webhook_unset",
    )
    async for client in _client(_app()):
        by_action = await client.get(
            "/v1/enforcement/deliveries",
            params={
                "trace_id": "tr-filt",
                "tenant_id": "t1",
                "action_id": deny,
            },
        )
        assert [row["action_id"] for row in by_action.json()["deliveries"]] == [deny]
        row = _row(by_action.json(), deny)
        assert row["last_status"] == "retrying"
        assert row["last_error"] == "timeout"
        assert row["acked_at"] is None

        by_status = await client.get(
            "/v1/enforcement/deliveries",
            params={
                "trace_id": "tr-filt",
                "tenant_id": "t1",
                "status": "not_configured",
            },
        )
        statuses = {row["last_status"] for row in by_status.json()["deliveries"]}
        assert statuses == {"not_configured"}

        dead = await client.get(
            "/v1/enforcement/deliveries",
            params={
                "trace_id": "tr-filt",
                "tenant_id": "t1",
                "status": "dead_lettered",
            },
        )
        assert dead.json()["deliveries"] == []


@pytest.mark.asyncio
async def test_dead_lettered_exposes_last_error(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setattr(
        "decision_api.enforcement._retry_wait", _zero_wait, raising=False
    )

    class _Http:
        async def post(self, *_a, **_k):
            raise RuntimeError("sink down")

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-dlq",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert out["journal"]["status"] == "dead_lettered"
    aid = out["action_id"]
    logical = logical_enforcement_delivery(aid)
    assert logical is not None
    async for client in _client(_app()):
        r = await client.get(
            "/v1/enforcement/deliveries",
            params={"trace_id": "tr-dlq", "tenant_id": "t1"},
        )
        row = _row(r.json(), aid)
        assert row["last_status"] == "dead_lettered"
        assert row["attempt_count"] == logical["attempt_count"]
        assert row["last_error"]
        assert row["acked_at"] is None


@pytest.mark.asyncio
async def test_requires_tenant_scoped_query_params(monkeypatch, tmp_path) -> None:
    _journal_env(monkeypatch, tmp_path)
    async for client in _client(_app()):
        missing = await client.get("/v1/enforcement/deliveries")
        assert missing.status_code == 422
        no_tenant = await client.get(
            "/v1/enforcement/deliveries", params={"trace_id": "tr-x"}
        )
        assert no_tenant.status_code == 422


def test_query_helpers_reuse_logical_delivery(monkeypatch, tmp_path) -> None:
    from decision_api.enforcement import query_enforcement_deliveries

    _journal_env(monkeypatch, tmp_path)
    aid = _seed(
        trace_id="tr-log",
        tenant_id="t1",
        status="acked",
        attempt_count=3,
    )
    logical = logical_enforcement_delivery(aid)
    rows = query_enforcement_deliveries(trace_id="tr-log", tenant_id="t1")
    assert logical is not None
    assert len(rows) == 1
    assert rows[0]["attempt_count"] == logical["attempt_count"] == 3
    assert rows[0]["action_id"] == aid


def test_source_is_not_promote_demote_or_crm() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "src" / "decision_api" / "enforcement.py"
    ).read_text(encoding="utf-8")
    router = (
        Path(__file__).resolve().parents[1] / "src" / "decision_api" / "product_ack.py"
    ).read_text(encoding="utf-8")
    blob = (src + "\n" + router).lower()
    assert "propose_demote" not in src
    assert "confirm_demote" not in src
    assert "/deliveries" in router
    assert "case crm" not in blob
    assert "assignee" not in blob
    assert "promote" not in router.lower() or "not promote" in router.lower()


def test_contract_and_claim_lock_journal_query_both_sides() -> None:
    contract = _CONTRACT.read_text(encoding="utf-8")
    claim = _CLAIM.read_text(encoding="utf-8")
    cl = contract.lower()
    ck = claim.lower()
    assert "/v1/enforcement/deliveries" in contract
    assert "trace_id" in cl
    assert "action_id" in cl
    assert "not_configured" in cl
    assert "journal" in cl and "query" in cl
    assert "product ack" in cl
    assert "http 2xx" in cl or "journal" in cl and "acked" in cl
    assert "case crm" in cl
    assert "d9.4" in cl
    assert "promote" in cl or "demote" in cl
    assert "journal queryable" in ck or "queryable by trace_id" in ck
    assert "case crm" in ck
    assert "god-view" in ck or "cross-tenant" in ck
    assert "d9.4" in ck
