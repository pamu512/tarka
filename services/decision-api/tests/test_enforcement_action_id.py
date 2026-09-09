"""G4.2: idempotent action_id on suggested_actions / webhook delivery."""

from __future__ import annotations

import json
import re

import pytest

from decision_api.enforcement import (
    ACTION_ID_SCHEME,
    apply_enforcement_adapters,
    idempotent_action_id,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


async def _deliver(
    monkeypatch,
    tmp_path,
    *,
    trace_id: str,
    tenant_id: str,
    decision: str,
    recommended_action: str | None = None,
    pack_hash: str = "",
) -> dict:
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )
    posts: list[dict] = []

    class _Resp:
        status_code = 204

    class _Http:
        async def post(self, url, content=None, headers=None, timeout=None):
            posts.append(json.loads(content.decode("utf-8")))
            return _Resp()

    await apply_enforcement_adapters(
        http=_Http(),
        trace_id=trace_id,
        tenant_id=tenant_id,
        entity_id="e1",
        event_type="payment",
        decision=decision,
        score=90.0,
        tags=["x"],
        recommended_action=recommended_action,
        pack_hash=pack_hash,
    )
    assert posts, "webhook must POST when URL is set"
    return posts[0]


@pytest.mark.asyncio
async def test_same_decision_retry_same_action_id(monkeypatch, tmp_path) -> None:
    kwargs = {"trace_id": "tr-retry", "tenant_id": "t1", "decision": "deny"}
    first = await _deliver(monkeypatch, tmp_path, **kwargs)
    second = await _deliver(monkeypatch, tmp_path, **kwargs)
    assert "deny" in first["suggested_actions"]
    assert isinstance(first["suggested_actions"], list)
    assert all(isinstance(t, str) for t in first["suggested_actions"])
    assert first["action_id"] == second["action_id"]
    assert _HEX64.fullmatch(first["action_id"])
    assert first["action_ids"]["deny"] == first["action_id"]


@pytest.mark.asyncio
async def test_different_trace_or_action_different_action_id(
    monkeypatch, tmp_path
) -> None:
    base = {"tenant_id": "t1"}
    deny_a = await _deliver(
        monkeypatch, tmp_path, trace_id="tr-a", decision="deny", **base
    )
    deny_b = await _deliver(
        monkeypatch, tmp_path, trace_id="tr-b", decision="deny", **base
    )
    review = await _deliver(
        monkeypatch, tmp_path, trace_id="tr-a", decision="review", **base
    )
    assert deny_a["action_id"] != deny_b["action_id"]
    assert deny_a["action_id"] != review["action_id"]
    assert deny_a["action_ids"]["deny"] != review["action_ids"]["review"]


def test_action_id_scheme_is_sha256_of_tenant_trace_action_pack() -> None:
    import hashlib

    material = "\n".join((ACTION_ID_SCHEME, "t1", "tr-retry", "deny", "pack-aaa"))
    expected = hashlib.sha256(material.encode("utf-8")).hexdigest()
    got = idempotent_action_id(
        tenant_id="t1",
        trace_id="tr-retry",
        action="deny",
        pack_hash="pack-aaa",
    )
    assert got == expected
    assert got != idempotent_action_id(
        tenant_id="t1",
        trace_id="tr-retry",
        action="deny",
        pack_hash="pack-bbb",
    )


@pytest.mark.asyncio
async def test_different_pack_hash_different_action_id(monkeypatch, tmp_path) -> None:
    a = await _deliver(
        monkeypatch,
        tmp_path,
        trace_id="tr-pack",
        tenant_id="t1",
        decision="deny",
        pack_hash="pack-aaa",
    )
    b = await _deliver(
        monkeypatch,
        tmp_path,
        trace_id="tr-pack",
        tenant_id="t1",
        decision="deny",
        pack_hash="pack-bbb",
    )
    assert a["action_id"] != b["action_id"]
    assert a["action_id"] == idempotent_action_id(
        tenant_id="t1",
        trace_id="tr-pack",
        action="deny",
        pack_hash="pack-aaa",
    )
