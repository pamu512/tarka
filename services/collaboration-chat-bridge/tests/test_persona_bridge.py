"""Copilot persona resolution for bridge → investigation-agent."""

from __future__ import annotations

import pytest
from collaboration_chat_bridge.config import Settings
from collaboration_chat_bridge.persona_bridge import (
    resolve_copilot_persona_for_bridge,
    strip_persona_command,
)


def test_strip_persona_variants():
    assert strip_persona_command("!orch Summarize") == ("Summarize", "orchestrator")
    assert strip_persona_command("!ORCHESTRATOR  x") == ("x", "orchestrator")
    assert strip_persona_command("!orch") == ("", "orchestrator")
    assert strip_persona_command("!inv Do work") == ("Do work", "investigation")
    assert strip_persona_command("!investigation Hi") == ("Hi", "investigation")
    assert strip_persona_command("no prefix") == ("no prefix", None)


def test_resolve_default_and_prefix():
    s = Settings()
    p, m = resolve_copilot_persona_for_bridge(s.default_copilot_persona, [{"role": "user", "content": "plain"}])
    assert p == "investigation"
    p2, m2 = resolve_copilot_persona_for_bridge("investigation", [{"role": "user", "content": "!orch Go"}])
    assert p2 == "orchestrator"
    assert m2[0]["content"] == "Go"


def test_resolve_explicit_wins_over_prefix():
    p, m = resolve_copilot_persona_for_bridge(
        "investigation",
        [{"role": "user", "content": "!orch ignored when explicit"}],
        explicit="investigation",
    )
    assert p == "investigation"
    assert m[0]["content"] == "!orch ignored when explicit"


@pytest.mark.asyncio
async def test_post_chat_payload_persona(monkeypatch: pytest.MonkeyPatch):
    from collaboration_chat_bridge import agent_client

    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "reply": "ok",
                "turn_id": "t1",
                "persona": captured.get("json", {}).get("persona"),
                "claims": [],
                "answer_sections": {},
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, **kw):
            captured["json"] = dict(json or {})
            return _Resp()

    monkeypatch.setattr(agent_client.httpx, "AsyncClient", lambda **k: _Client())
    settings = Settings(default_copilot_persona="investigation")
    out = await agent_client.post_chat(
        settings,
        tenant_id="ten",
        analyst_id="a1",
        messages=[{"role": "user", "content": "!orch hello"}],
    )
    assert captured["json"]["persona"] == "orchestrator"
    assert captured["json"]["messages"][0]["content"] == "hello"
    assert out.get("persona") == "orchestrator"
