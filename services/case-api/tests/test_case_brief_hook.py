"""Case brief hook must persist brief_markdown as a CaseComment."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_fire_case_brief_persists_markdown_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://investigation.test")
    from case_api import agent_hooks

    brief_md = "# Case brief (deterministic)\n\n- case_id: `c1`"
    http = AsyncMock()
    resp = MagicMock()
    resp.content = b'{"ok":true}'
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"ok": True, "brief_markdown": brief_md, "llm_used": False})
    http.post = AsyncMock(return_value=resp)

    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    case_id = uuid.uuid4()

    await agent_hooks.fire_case_brief(
        http,
        {"id": str(case_id), "tenant_id": "t1", "title": "x"},
        session=session,
        case_id=case_id,
    )

    assert session.add.called
    comment = session.add.call_args[0][0]
    assert comment.author == "system"
    assert "Case brief (deterministic)" in comment.body
    assert "LLM provider" not in comment.body
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_fire_case_brief_rejects_llm_used_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://investigation.test")
    from case_api import agent_hooks

    http = AsyncMock()
    resp = MagicMock()
    resp.content = b"{}"
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={"ok": True, "brief_markdown": "should not persist", "llm_used": True}
    )
    http.post = AsyncMock(return_value=resp)
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    case_id = uuid.uuid4()

    await agent_hooks.fire_case_brief(
        http, {"id": str(case_id)}, session=session, case_id=case_id
    )
    comment = session.add.call_args[0][0]
    assert "deterministic" in comment.body
    assert "should not persist" not in comment.body


@pytest.mark.asyncio
async def test_fire_case_brief_fallback_not_llm_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://investigation.test")
    from case_api import agent_hooks

    http = AsyncMock()
    http.post = AsyncMock(side_effect=RuntimeError("down"))
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    case_id = uuid.uuid4()

    await agent_hooks.fire_case_brief(
        http,
        {"id": str(case_id), "tenant_id": "t1"},
        session=session,
        case_id=case_id,
    )

    comment = session.add.call_args[0][0]
    assert "case-brief unreachable" in comment.body
    assert "LLM" not in comment.body
