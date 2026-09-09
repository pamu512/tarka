"""W8 emit_only vs handoff: pack-why identical; authority differs."""

from __future__ import annotations

import json

import pytest

from decision_api.enforcement import (
    apply_enforcement_adapters,
    enforcement_mode,
    suggested_actions,
)
from desk_provision import enforcement_mode as desk_enforcement_mode


def test_default_emit_only(monkeypatch) -> None:
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    assert enforcement_mode() == "emit_only"
    assert desk_enforcement_mode() == "emit_only"


def test_unset_env_and_desk_file_without_mode_is_emit_only(
    tmp_path, monkeypatch
) -> None:
    provision = tmp_path / "desk_provision.json"
    provision.write_text(
        json.dumps({"schema_id": "tarka.desk_provision/v1", "profile": "demo"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(provision))
    assert enforcement_mode() == "emit_only"
    assert desk_enforcement_mode() == "emit_only"


@pytest.mark.parametrize("raw", ["", "block", "enforce", "ALLOW", "deny"])
def test_invalid_or_empty_env_is_emit_only(monkeypatch, raw: str) -> None:
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.setenv("TARKA_ENFORCEMENT_MODE", raw)
    assert enforcement_mode() == "emit_only"
    assert desk_enforcement_mode() == "emit_only"


def test_handoff_only_when_mode_explicitly_set(monkeypatch) -> None:
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    assert enforcement_mode() == "emit_only"
    monkeypatch.setenv("TARKA_ENFORCEMENT_MODE", "handoff")
    assert enforcement_mode() == "handoff"
    assert desk_enforcement_mode() == "handoff"


def test_desk_contract_handoff_only_when_mode_set(tmp_path, monkeypatch) -> None:
    provision = tmp_path / "desk_provision.json"
    provision.write_text(
        json.dumps(
            {
                "schema_id": "tarka.desk_provision/v1",
                "enforcement": {"mode": "handoff"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.setenv("TARKA_DESK_PROVISION_PATH", str(provision))
    assert enforcement_mode() == "handoff"
    assert desk_enforcement_mode() == "handoff"


def test_suggested_actions_always() -> None:
    assert "deny" in suggested_actions("deny", None)
    assert "hold_payout" in suggested_actions("review", "hold_payout")
    assert suggested_actions("allow", None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,event,authority",
    [("emit_only", "decision.emitted", False), ("handoff", "decision.enforced", True)],
)
async def test_mode_changes_authority_not_action(
    monkeypatch, tmp_path, mode, event, authority
) -> None:
    monkeypatch.setenv("TARKA_ENFORCEMENT_MODE", mode)
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

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert out["enforcement_action"] == "block"
    assert out["enforcement_mode"] == mode
    assert out["authority"] is authority
    assert out["webhook_event"] == event
    assert posts[0]["webhook_event"] == event
    assert posts[0]["authority"] is authority
    assert "deny" in posts[0]["suggested_actions"]


@pytest.mark.asyncio
async def test_emit_only_never_claims_enforced_block(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TARKA_ENFORCEMENT_MODE", raising=False)
    monkeypatch.delenv("TARKA_DESK_PROVISION_PATH", raising=False)
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

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-emit",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
    )
    assert out["enforcement_action"] == "block"
    assert out["enforcement_mode"] == "emit_only"
    assert out["authority"] is False
    assert out["webhook_event"] == "decision.emitted"
    body = posts[0]
    assert body["authority"] is False
    assert body["enforcement_mode"] == "emit_only"
    assert body["webhook_event"] == "decision.emitted"
    blob = json.dumps({"summary": out, "payload": body}).lower()
    assert "we blocked" not in blob
    assert "enforced block" not in blob
    assert "silent block" not in blob
