"""Gate: Ollama must respond 200 on ``GET /api/tags`` before exercising ``OllamaLLMClient``."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHADOW_SRC = _REPO_ROOT / "tarka_v2_core" / "services" / "shadow_agent" / "src"
if str(_SHADOW_SRC) not in sys.path:
    sys.path.insert(0, str(_SHADOW_SRC))

from shadow_agent.llm_client import OllamaLLMClient  # noqa: E402


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")


def test_llm_client_gate_ping_200_then_chat_round_trip() -> None:
    """Plain ``httpx`` gate (200), then pooled client ``ping`` and ``chat`` with ``format=json``."""

    base = _ollama_base()

    async def _run() -> None:
        async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(15.0)) as gate_client:
            gate = await gate_client.get("/api/tags")
        assert gate.status_code == 200, (
            "Gate failed: Ollama must return HTTP 200 on GET /api/tags before llm_client tests "
            f"(base={base!r}, status={gate.status_code})"
        )

        async with OllamaLLMClient(base_url=base) as client:
            pr = await client.ping()
            assert pr.status_code == 200

            payload = await client.chat(
                [{"role": "user", "content": 'Reply with JSON only: {"ok": true, "n": 1}'}],
                model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
                format_json=True,
            )
            assert isinstance(payload, dict)
            assert "message" in payload
            msg = payload["message"]
            assert isinstance(msg, dict)
            assert "content" in msg

    asyncio.run(_run())
