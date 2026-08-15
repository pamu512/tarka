"""SHADOW_LLM_BACKEND presets for evaluate (OpenAI-compatible) and factory."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from llm_client import OpenAICompatLLMClient, build_shadow_llm_client
from providers.factory import get_llm_provider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider


def test_build_default_is_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHADOW_LLM_BACKEND", raising=False)
    from llm_client import OllamaLLMClient

    client = build_shadow_llm_client()
    assert isinstance(client, OllamaLLMClient)
    asyncio.run(client.aclose())


def test_build_claude_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SHADOW_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_shadow_llm_client()


def test_build_claude_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = build_shadow_llm_client()
    assert isinstance(client, OpenAICompatLLMClient)
    assert client._base_url == "https://api.anthropic.com/v1"
    assert client._default_model == "claude-sonnet-4-5"
    asyncio.run(client.aclose())


def test_build_gemini_and_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    g = build_shadow_llm_client()
    assert "generativelanguage.googleapis.com" in g._base_url
    asyncio.run(g.aclose())
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "ds-test")
    q = build_shadow_llm_client()
    assert "dashscope.aliyuncs.com" in q._base_url
    asyncio.run(q.aclose())


def test_self_hosted_requires_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "self-hosted")
    monkeypatch.delenv("SHADOW_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="SHADOW_LLM_BASE_URL"):
        build_shadow_llm_client()


def test_self_hosted_vllm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "vllm")
    monkeypatch.setenv("SHADOW_LLM_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("SHADOW_LLM_MODEL", "qwen2.5:14b")
    client = build_shadow_llm_client()
    assert client._base_url == "http://vllm:8000/v1"
    assert client._default_model == "qwen2.5:14b"
    asyncio.run(client.aclose())


def test_compat_chat_maps_openai_envelope() -> None:
    async def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gemini-2.0-flash"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"risk_level":"LOW"}'}}]},
        )

    transport = httpx.MockTransport(_handler)

    async def _run() -> None:
        http = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            transport=transport,
        )
        client = OpenAICompatLLMClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gemini-2.0-flash",
            api_key="k",
            client=http,
        )
        out = await client.chat_json_validated([{"role": "user", "content": "x"}])
        assert out == {"risk_level": "LOW"}
        await client.aclose()

    asyncio.run(_run())


def test_analyze_factory_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = get_llm_provider()
    assert isinstance(p, OpenAIProvider)
    asyncio.run(p.aclose())


def test_analyze_factory_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "ollama")
    assert isinstance(get_llm_provider(), OllamaProvider)
