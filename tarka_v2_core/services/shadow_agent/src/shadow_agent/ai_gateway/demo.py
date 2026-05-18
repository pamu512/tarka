"""Demo / local marketplace: Ollama at localhost with optional concurrency throttle."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

from shadow_agent.ai_gateway.base import AIGateway

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_OLLAMA = "http://localhost:11434"


class DemoAIGateway(AIGateway):
    """
    Routes Shadow investigate traffic to **Ollama** (default ``http://localhost:11434``).

    Uses an ``asyncio.Semaphore`` so constrained laptops can set ``AI_GATEWAY_MAX_CONCURRENT=1``
    via ``docker-compose.local.yml`` while production-like integration tests can raise the limit.
    """

    def __init__(self, *, base_url: str, max_concurrent: int) -> None:
        self._base = base_url.rstrip("/")
        n = max(1, int(max_concurrent))
        self._sem = asyncio.Semaphore(n)
        logger.info(
            "ai_gateway_demo base_url=%s max_concurrent=%s",
            self._base,
            n,
        )

    @classmethod
    def from_environment(cls) -> DemoAIGateway:
        raw = (os.environ.get("AI_GATEWAY_OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or _DEFAULT_OLLAMA).strip()
        base = raw.rstrip("/") or _DEFAULT_OLLAMA
        mc = int((os.environ.get("AI_GATEWAY_MAX_CONCURRENT") or "32").strip() or "32")
        return cls(base_url=base, max_concurrent=mc)

    @property
    def shadow_investigate_base_url(self) -> str:
        return self._base

    @property
    def saarthi_llm_base_url(self) -> str | None:
        # Local Saarthi may still use Ollama for drafts unless SAARTHI_GEMINI_URL is set.
        return (os.environ.get("SAARTHI_GEMINI_URL") or "").strip() or None

    async def run_shadow_investigate_inference(self, coro: Callable[[], Awaitable[T]]) -> T:
        async with self._sem:
            return await coro()
