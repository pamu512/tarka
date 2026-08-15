"""Resolve ``BaseLLMProvider`` from ``SHADOW_LLM_BACKEND``."""

from __future__ import annotations

import logging
import os

from providers.base import BaseLLMProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

_MISSING_BACKEND_WARNED = False

_OPENAI_ALIASES = frozenset(
    {
        "openai",
        "claude",
        "anthropic",
        "gemini",
        "qwen",
        "dashscope",
        "self_hosted",
        "vllm",
        "openai_compat",
        "openai_compatible",
    },
)


def _first_env(*keys: str) -> str:
    for key in keys:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return ""


def get_llm_provider() -> BaseLLMProvider:
    """
    Factory: ``SHADOW_LLM_BACKEND`` → concrete provider.

    Values (case-insensitive): ``ollama`` (default), ``openai``, ``claude``,
    ``gemini``, ``qwen``, ``self-hosted`` / ``vllm``.
    """
    global _MISSING_BACKEND_WARNED

    raw = os.environ.get("SHADOW_LLM_BACKEND", "").strip().lower().replace("-", "_")

    if not raw:
        if not _MISSING_BACKEND_WARNED:
            logger.warning(
                "SHADOW_LLM_BACKEND is unset; defaulting to ollama "
                "(ollama|openai|claude|gemini|qwen|self-hosted)",
            )
            _MISSING_BACKEND_WARNED = True
        return OllamaProvider()

    if raw == "ollama":
        return OllamaProvider()

    if raw not in _OPENAI_ALIASES:
        logger.warning(
            "unknown SHADOW_LLM_BACKEND=%r; defaulting to ollama",
            os.environ.get("SHADOW_LLM_BACKEND", ""),
        )
        return OllamaProvider()

    model = _first_env("SHADOW_LLM_MODEL", "OPENAI_MODEL")
    key = _first_env("SHADOW_LLM_API_KEY")
    base = _first_env("SHADOW_LLM_BASE_URL", "OPENAI_BASE_URL")
    if raw in ("claude", "anthropic"):
        return OpenAIProvider(
            model=model or "claude-sonnet-4-5",
            api_key=key or _first_env("ANTHROPIC_API_KEY"),
            base_url=base or "https://api.anthropic.com/v1",
        )
    if raw == "gemini":
        return OpenAIProvider(
            model=model or "gemini-2.0-flash",
            api_key=key or _first_env("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            base_url=base or "https://generativelanguage.googleapis.com/v1beta/openai",
        )
    if raw in ("qwen", "dashscope"):
        return OpenAIProvider(
            model=model or "qwen-plus",
            api_key=key or _first_env("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
            base_url=base or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    if raw in ("self_hosted", "vllm", "openai_compat", "openai_compatible"):
        if not base:
            raise ValueError(
                "SHADOW_LLM_BACKEND=self-hosted|vllm requires SHADOW_LLM_BASE_URL",
            )
        return OpenAIProvider(
            model=model or "llama3.2",
            api_key=key or _first_env("OPENAI_API_KEY") or "not-needed",
            base_url=base,
        )
    return OpenAIProvider(
        model=model or "gpt-4o-mini",
        api_key=key or _first_env("OPENAI_API_KEY"),
        base_url=base or None,
    )
