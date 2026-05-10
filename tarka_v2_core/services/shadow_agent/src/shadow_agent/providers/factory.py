"""Resolve ``BaseLLMProvider`` from ``SHADOW_LLM_BACKEND``."""

from __future__ import annotations

import logging
import os

from shadow_agent.providers.base import BaseLLMProvider
from shadow_agent.providers.ollama_provider import OllamaProvider
from shadow_agent.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

_MISSING_BACKEND_WARNED = False


def get_llm_provider() -> BaseLLMProvider:
    """
    Factory: ``SHADOW_LLM_BACKEND`` → concrete provider.

    Values (case-insensitive):

    - ``ollama`` → :class:`OllamaProvider`
    - ``openai`` → :class:`OpenAIProvider`

    If unset, defaults to **ollama** and emits a one-time **warning** at first call.
    Unknown values default to **ollama** with a warning (each occurrence).
    """
    global _MISSING_BACKEND_WARNED

    raw = os.environ.get("SHADOW_LLM_BACKEND", "").strip().lower()

    if not raw:
        if not _MISSING_BACKEND_WARNED:
            logger.warning(
                "SHADOW_LLM_BACKEND is unset; defaulting to ollama (set SHADOW_LLM_BACKEND=ollama|openai)",
            )
            _MISSING_BACKEND_WARNED = True
        return OllamaProvider()

    if raw == "ollama":
        return OllamaProvider()

    if raw == "openai":
        return OpenAIProvider()

    logger.warning(
        "unknown SHADOW_LLM_BACKEND=%r; defaulting to ollama",
        os.environ.get("SHADOW_LLM_BACKEND", ""),
    )
    return OllamaProvider()
