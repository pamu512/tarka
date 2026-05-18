"""Factory: ``SHADOW_LLM_BACKEND`` → provider instance."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_get_llm_provider_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-factory")
    from shadow_agent.providers.factory import get_llm_provider
    from shadow_agent.providers.openai_provider import OpenAIProvider

    provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)

    async def _close() -> None:
        await provider.aclose()

    asyncio.run(_close())


def test_get_llm_provider_ollama_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "ollama")
    from shadow_agent.providers.factory import get_llm_provider
    from shadow_agent.providers.ollama_provider import OllamaProvider

    provider = get_llm_provider()
    assert isinstance(provider, OllamaProvider)

    async def _close() -> None:
        await provider.aclose()

    asyncio.run(_close())
