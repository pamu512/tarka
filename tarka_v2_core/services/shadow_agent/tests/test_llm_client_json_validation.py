"""Mocked HTTP tests for ``chat_json_validated`` JSON parse + self-correction + ``ShadowLLMError``."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.llm_client import (  # noqa: E402
    OllamaLLMClient,
    ShadowLLMError,
    _JSON_FIX_USER_PROMPT,
)


def _chat_envelope(content: str) -> dict[str, Any]:
    return {
        "model": "mock",
        "created_at": "0001-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


def test_chat_json_validated_exhausted_raises_shadow_llm_error_after_three_calls() -> None:
    """Malformed JSON on every attempt: two self-corrections then ``ShadowLLMError``."""

    async def _run() -> tuple[int, ShadowLLMError]:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            assert request.method == "POST"
            assert str(request.url).endswith("/api/chat")
            req_body = json.loads(request.content.decode())
            assert req_body.get("format") == "json"
            assert req_body.get("stream") is False
            return httpx.Response(200, json=_chat_envelope("{ not valid json"))

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://ollama.test:11434",
            timeout=httpx.Timeout(10.0),
        ) as http_client:
            client = OllamaLLMClient(base_url="http://ollama.test:11434", client=http_client)
            try:
                await client.chat_json_validated(
                    [{"role": "user", "content": "Return JSON."}],
                    model="llama3.2",
                    json_self_correction_retries=2,
                )
            except ShadowLLMError as e:
                return call_count, e
            finally:
                await client.aclose()
            raise AssertionError("expected ShadowLLMError")

    calls, err = asyncio.run(_run())
    assert calls == 3
    assert err.reason == "json_decode_exhausted"
    assert err.parse_attempts == 3
    assert isinstance(err.__cause__, json.JSONDecodeError)
    assert err.raw_content is not None
    assert "{ not valid json" in err.raw_content


def test_chat_json_validated_second_round_succeeds() -> None:
    """First body invalid JSON; second parse succeeds after self-correction."""

    async def _run() -> tuple[Any, int]:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(200, json=_chat_envelope("not json {"))
            return httpx.Response(200, json=_chat_envelope('{"fixed": true, "n": 2}'))

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://ollama.test:11434",
            timeout=httpx.Timeout(10.0),
        ) as http_client:
            client = OllamaLLMClient(base_url="http://ollama.test:11434", client=http_client)
            try:
                out = await client.chat_json_validated(
                    [{"role": "user", "content": "emit json"}],
                    model="m",
                )
                return out, len(calls)
            finally:
                await client.aclose()

    parsed, n_calls = asyncio.run(_run())
    assert n_calls == 2
    assert parsed == {"fixed": True, "n": 2}


def test_chat_json_validated_correction_request_includes_fix_prompt_and_broken_json() -> None:
    """Second HTTP request must include invalid assistant text and the strict fix user line."""

    async def _run() -> None:
        bodies: list[list[dict[str, Any]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            req = json.loads(request.content.decode())
            bodies.append(req["messages"])
            if len(bodies) == 1:
                return httpx.Response(200, json=_chat_envelope("{broken"))
            return httpx.Response(200, json=_chat_envelope('{"ok":true}'))

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://ollama.test:11434",
            timeout=httpx.Timeout(10.0),
        ) as http_client:
            client = OllamaLLMClient(base_url="http://ollama.test:11434", client=http_client)
            try:
                await client.chat_json_validated([{"role": "user", "content": "x"}], model="m")
            finally:
                await client.aclose()

        assert len(bodies) == 2
        second = bodies[1]
        assert second[-1]["role"] == "user"
        assert second[-1]["content"] == _JSON_FIX_USER_PROMPT
        assert second[-2]["role"] == "assistant"
        assert "{broken" in second[-2]["content"]

    asyncio.run(_run())
