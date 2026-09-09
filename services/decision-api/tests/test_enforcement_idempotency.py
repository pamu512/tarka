"""D9.2: retry POSTs reuse G4.2 action_id as the idempotency key. No second id."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from decision_api.enforcement import (
    apply_enforcement_adapters,
    idempotent_action_id,
    read_enforcement_journal,
)

_REPO = Path(__file__).resolve().parents[3]
_CONTRACT = _REPO / "docs" / "contracts" / "enforcement-v1.md"
_CLAIM = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_MOCK = _REPO / "scripts" / "oss" / "enforcement_webhook_mock.py"


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _journal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )


def _emit_only(monkeypatch) -> None:
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)


async def _zero_wait(_attempt: int) -> None:
    return None


def _load_mock():
    spec = importlib.util.spec_from_file_location("enforcement_webhook_mock", _MOCK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _retrying_deny(
    monkeypatch, tmp_path, *, trace_id: str, tenant_id: str = "t1"
):
    _emit_only(monkeypatch)
    _journal(tmp_path, monkeypatch)
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setattr(
        "decision_api.enforcement._retry_wait", _zero_wait, raising=False
    )
    posts: list[dict] = []
    codes = [503, 503, 200]

    class _Http:
        async def post(self, *_a, content=None, **_k):
            posts.append(json.loads(content.decode("utf-8")))
            return _Resp(codes[len(posts) - 1] if len(posts) <= len(codes) else 200)

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id=trace_id,
        tenant_id=tenant_id,
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
        pack_hash="pack-d92",
    )
    return out, posts


@pytest.mark.asyncio
async def test_retry_attempts_share_same_action_id_and_idempotency_key(
    monkeypatch, tmp_path
) -> None:
    out, posts = await _retrying_deny(monkeypatch, tmp_path, trace_id="tr-d92-same")
    assert out["enforcement_mode"] == "emit_only"
    assert out["webhook"]["ok"] is True
    assert len(posts) == 3
    expected = idempotent_action_id(
        tenant_id="t1",
        trace_id="tr-d92-same",
        action="deny",
        pack_hash="pack-d92",
    )
    keys = {(p["action_id"], p["idempotency_key"]) for p in posts}
    assert keys == {(expected, expected)}
    rows = read_enforcement_journal(10)
    assert [r["status"] for r in rows] == ["retrying", "retrying", "acked"]
    assert {r["action_id"] for r in rows} == {expected}
    assert {r["idempotency_key"] for r in rows} == {expected}
    assert out.get("blocked") is not True
    assert out.get("evaluate_blocked") is None


@pytest.mark.asyncio
async def test_distinct_decisions_get_distinct_keys(monkeypatch, tmp_path) -> None:
    _emit_only(monkeypatch)
    _journal(tmp_path, monkeypatch)
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setattr(
        "decision_api.enforcement._retry_wait", _zero_wait, raising=False
    )
    captured: list[dict] = []

    class _Http:
        async def post(self, *_a, content=None, **_k):
            captured.append(json.loads(content.decode("utf-8")))
            return _Resp(204)

    async def _once(**kwargs):
        return await apply_enforcement_adapters(
            http=_Http(),
            entity_id="e1",
            event_type="payment",
            score=90.0,
            tags=["x"],
            pack_hash="pack-d92",
            **kwargs,
        )

    await _once(trace_id="tr-a", tenant_id="t1", decision="deny")
    await _once(trace_id="tr-b", tenant_id="t1", decision="deny")
    await _once(trace_id="tr-a", tenant_id="t1", decision="review")
    assert [p["action_id"] for p in captured] == [
        p["idempotency_key"] for p in captured
    ]
    deny_a, deny_b, review = captured
    assert deny_a["action_id"] != deny_b["action_id"]
    assert deny_a["action_id"] != review["action_id"]
    assert deny_a["action_ids"]["deny"] != review["action_ids"]["review"]
    rows = read_enforcement_journal(10)
    journal_keys = {r["action_id"] for r in rows}
    assert journal_keys == {
        deny_a["action_id"],
        deny_b["action_id"],
        review["action_id"],
    }


@pytest.mark.asyncio
async def test_journal_dedupe_by_action_id_one_logical_delivery(
    monkeypatch, tmp_path
) -> None:
    from decision_api.enforcement import logical_enforcement_delivery

    out, posts = await _retrying_deny(monkeypatch, tmp_path, trace_id="tr-d92-dedupe")
    key = posts[0]["action_id"]
    assert posts[0]["idempotency_key"] == key
    assert out["journal"]["status"] == "acked"
    raw_rows = [
        r
        for r in read_enforcement_journal(20)
        if r.get("action_id") == key or r.get("idempotency_key") == key
    ]
    assert len(raw_rows) == 3
    logical = logical_enforcement_delivery(key)
    assert logical is not None
    assert logical["action_id"] == key
    assert logical["idempotency_key"] == key
    assert logical["attempt_count"] == 3
    assert logical["status"] == "acked"
    other = logical_enforcement_delivery(
        idempotent_action_id(
            tenant_id="t1",
            trace_id="tr-other",
            action="deny",
            pack_hash="pack-d92",
        )
    )
    assert other is None


def test_mock_consumer_proves_same_key_on_retry() -> None:
    mock = _load_mock()
    key = idempotent_action_id(
        tenant_id="t1", trace_id="tr-mock", action="deny", pack_hash="pack-d92"
    )
    seen: dict[str, int] = {}
    first = mock.note_delivery(
        {"action_id": key, "idempotency_key": key, "suggested_actions": ["deny"]},
        seen=seen,
    )
    second = mock.note_delivery(
        {"action_id": key, "idempotency_key": key, "suggested_actions": ["deny"]},
        seen=seen,
    )
    assert first["action_id"] == second["action_id"] == key
    assert first["idempotency_key"] == second["idempotency_key"] == key
    assert first["attempt_count"] == 1
    assert second["attempt_count"] == 2
    assert first["duplicate"] is False
    assert second["duplicate"] is True


def test_contract_documents_g42_key_no_second_id() -> None:
    text = _CONTRACT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "tarka.action_id/v1" in text
    assert "tenant_id" in text
    assert "trace_id" in lowered
    assert "pack hash" in lowered or "pack_hash" in lowered
    assert "idempotency_key" in lowered
    assert "attempt_count" in lowered
    assert "logical delivery" in lowered or "one logical" in lowered
    assert "silent block" in lowered
    assert "delivery_id" not in lowered or "alias" in lowered
    assert "d9.3" in lowered
    assert "d9.4" in lowered
    assert "same-key retry lock is d9.2" not in lowered


def test_claim_lock_idempotency_both_sides() -> None:
    text = _CLAIM.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "action_id" in lowered
    assert "idempotency" in lowered
    assert "attempt_count" in lowered
    assert "silent block" in lowered
    assert "holds" in lowered or "payout" in lowered
    assert "case crm" in lowered or "crm ticket" in lowered
    assert "second" in lowered or "competing" in lowered or "delivery_id" in lowered
