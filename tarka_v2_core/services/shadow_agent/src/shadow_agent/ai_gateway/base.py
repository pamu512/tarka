"""Abstract routing for Shadow / SAR / dispute LLM traffic (Ollama demo vs cloud backends)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AIGateway(ABC):
    """Routes inference requests and optional concurrency policy (demo vs cloud)."""

    @property
    @abstractmethod
    def shadow_investigate_base_url(self) -> str:
        """HTTP origin for Shadow fraud workflows (Ollama-compatible ``/api/chat``)."""

    @property
    def saarthi_llm_base_url(self) -> str | None:
        """Optional REST origin for Saarthi SAR drafting (e.g. Gemini OpenAI-compat proxy)."""
        return None

    @abstractmethod
    async def run_shadow_investigate_inference(self, coro: Callable[[], Awaitable[T]]) -> T:
        """Execute one Shadow ``shadow.investigate`` / sidecar inference (demo may throttle)."""

    async def run_saarthi_inference(self, coro: Callable[[], Awaitable[T]]) -> T:
        """Saarthi SAR narrative / PDF pipeline LLM calls — cloud uses Gemini without global locks."""
        return await coro()
