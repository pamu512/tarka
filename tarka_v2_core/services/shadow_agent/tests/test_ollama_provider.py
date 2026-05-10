"""Ollama provider: httpx-mocked Ollama ``/api/chat`` + strict Pydantic validation."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.providers.ollama_provider import OllamaProvider  # noqa: E402


class _ShadowDecision(BaseModel):
    """Minimal decision envelope used by the gate test."""

    decision: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


def _chat_json_response(content_obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "mock",
        "created_at": "0001-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": json.dumps(content_obj)},
        "done": True,
    }


def test_ollama_provider_returns_valid_pydantic() -> None:
    """Happy path: Ollama returns JSON string; provider validates to ``_ShadowDecision``."""

    async def _run() -> _ShadowDecision:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert str(request.url).endswith("/api/chat")
            body = json.loads(request.content.decode())
            assert body.get("format") == "json"
            assert body.get("stream") is False
            return httpx.Response(
                200,
                json=_chat_json_response({"decision": "FLAG_REVIEW", "confidence": 0.82}),
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OllamaProvider(
                base_url="http://ollama.test:11434",
                model="llama3.2",
                client=client,
                max_json_retries=3,
            )
            try:
                return await provider.generate_decision(
                    "Classify this transaction as APPROVE or FLAG_REVIEW.",
                    _ShadowDecision,
                )
            finally:
                await provider.aclose()

    out = asyncio.run(_run())
    assert isinstance(out, _ShadowDecision)
    assert out.decision == "FLAG_REVIEW"
    assert out.confidence == pytest.approx(0.82)


def test_ollama_provider_json_validation_retry_then_success() -> None:
    """First model payload fails Pydantic; second attempt succeeds (retry loop)."""

    async def _run() -> _ShadowDecision:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json=_chat_json_response({"decision": "", "confidence": 2.0}),
                )
            return httpx.Response(
                200,
                json=_chat_json_response({"decision": "APPROVE", "confidence": 0.1}),
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OllamaProvider(
                base_url="http://ollama.test:11434",
                model="m",
                client=client,
                max_json_retries=4,
            )
            try:
                out = await provider.generate_decision("decide", _ShadowDecision)
                return out, calls
            finally:
                await provider.aclose()

    out, calls = asyncio.run(_run())
    assert len(calls) == 2
    assert out.decision == "APPROVE"
    assert out.confidence == pytest.approx(0.1)
