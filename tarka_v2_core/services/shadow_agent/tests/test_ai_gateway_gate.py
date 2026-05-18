"""Gate: AI gateway mode + Shadow LLM path uses gateway wrapper."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_build_ai_gateway_demo_vs_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    from shadow_agent.ai_gateway.cloud import CloudAIGateway
    from shadow_agent.ai_gateway.demo import DemoAIGateway
    from shadow_agent.ai_gateway.factory import build_ai_gateway

    monkeypatch.setenv("ENVIRONMENT", "development")
    assert isinstance(build_ai_gateway(), DemoAIGateway)

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AI_GATEWAY_MODE", "demo")
    assert isinstance(build_ai_gateway(), DemoAIGateway)

    monkeypatch.delenv("AI_GATEWAY_MODE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert isinstance(build_ai_gateway(), CloudAIGateway)


def test_demo_gateway_serializes_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two concurrent chats are serialized when ``AI_GATEWAY_MAX_CONCURRENT=1``."""
    from shadow_agent.ai_gateway.demo import DemoAIGateway
    from shadow_agent.llm_client import OllamaLLMClient

    monkeypatch.setenv("AI_GATEWAY_MAX_CONCURRENT", "1")
    gw = DemoAIGateway.from_environment()

    calls: list[str] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        calls.append("in")
        await asyncio.sleep(0.05)
        calls.append("out")
        return httpx.Response(
            200,
            json={"model": "x", "message": {"role": "assistant", "content": "{}"}},
        )

    async def _run() -> None:
        transport_obj = httpx.MockTransport(transport)
        async with httpx.AsyncClient(transport=transport_obj, base_url="http://ollama.test") as raw_client:
            client = OllamaLLMClient(client=raw_client, ai_gateway=gw)

            async def one_chat() -> None:
                await client.chat([{"role": "user", "content": "hi"}], format_json=True)

            await asyncio.gather(one_chat(), one_chat())

    asyncio.run(_run())

    assert calls == ["in", "out", "in", "out"]


def test_cloud_gateway_allows_parallel_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    from shadow_agent.ai_gateway.cloud import CloudAIGateway
    from shadow_agent.llm_client import OllamaLLMClient

    monkeypatch.setenv("SHADOW_VLLM_BASE_URL", "http://vllm.test")
    gw = CloudAIGateway.from_environment()
    calls: list[str] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        calls.append("in")
        await asyncio.sleep(0.03)
        calls.append("out")
        return httpx.Response(
            200,
            json={"model": "x", "message": {"role": "assistant", "content": "{}"}},
        )

    async def _run() -> None:
        transport_obj = httpx.MockTransport(transport)
        async with httpx.AsyncClient(transport=transport_obj, base_url="http://vllm.test") as raw_client:
            client = OllamaLLMClient(client=raw_client, ai_gateway=gw)

            async def one_chat() -> None:
                await client.chat([{"role": "user", "content": "hi"}], format_json=True)

            await asyncio.gather(one_chat(), one_chat())

    asyncio.run(_run())

    assert calls.count("in") == 2
