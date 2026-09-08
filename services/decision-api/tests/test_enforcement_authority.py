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
    assert enforcement_mode() == "emit_only"
    assert desk_enforcement_mode() == "emit_only"


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
