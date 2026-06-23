"""Gate (Prompt 132): broken JSON is repaired on the second parse attempt via the retry loop."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

_SERVICES = Path(__file__).resolve().parents[2]
if str(_SERVICES) not in sys.path:
    sys.path.insert(0, str(_SERVICES))

from shadow.inference.retry_logic import (  # noqa: E402
    loads_json_with_ollama_repair,
    loads_json_with_repair,
    ollama_fix_messages,
)


def test_ollama_fix_messages_include_parse_error_and_snippet() -> None:
    msgs = ollama_fix_messages(broken_text='{"x":', error_message="Expecting value")
    assert any("Parse error" in m["content"] for m in msgs if m["role"] == "user")
    assert '{"x":' in next(m["content"] for m in msgs if m["role"] == "user")


def test_broken_json_repaired_on_second_attempt() -> None:
    """First ``json.loads`` fails; ``repair`` returns valid JSON; second attempt succeeds."""
    calls: list[tuple[str, str]] = []

    async def fake_repair(broken: str, err: str) -> str:
        calls.append((broken, err))
        assert "broken" in broken
        assert "JSONDecodeError" in err or "Expecting" in err
        return json.dumps({"status": "ok", "gate": 132})

    bad = '{"status": "broken"'  # missing closing brace

    out = asyncio.run(
        loads_json_with_repair(bad, repair=fake_repair, max_repairs=1),
    )
    assert out == {"status": "ok", "gate": 132}
    assert len(calls) == 1


def test_loads_json_with_ollama_repair_uses_http_client_mock() -> None:
    """Second body from mocked Ollama returns valid JSON; loop exits without live server."""
    fixed = json.dumps({"repaired": True})

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body.get("format") == "json"
        assert body.get("model") == "stub-model"
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": fixed}},
        )

    transport = httpx.MockTransport(handler)
    bad = '{"a":1,'  # trailing comma invalid in strict JSON

    async def _run() -> object:
        async with httpx.AsyncClient(transport=transport, base_url="http://ollama.test") as client:
            return await loads_json_with_ollama_repair(
                bad,
                client=client,
                model="stub-model",
                max_repairs=1,
            )

    out = asyncio.run(_run())
    assert out == {"repaired": True}
