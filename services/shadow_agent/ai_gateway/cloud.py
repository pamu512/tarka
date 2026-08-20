"""Cloud: load-balanced vLLM (Ollama-compatible) or Gemini proxy — no single-instance throttle."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ai_gateway.base import AIGateway

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CloudAIGateway(AIGateway):
    """
    High-throughput routing:

    * ``SHADOW_VLLM_BASE_URL`` / ``SHADOW_LLM_BASE_URL`` — vLLM or OpenAI-compatible LB (Llama 3.2 on g5, etc.).
    * ``SAARTHI_GEMINI_URL`` — optional OpenAI-compat proxy to Gemini for SAR drafting.
    """

    def __init__(
        self,
        *,
        shadow_base_url: str,
        sar_url: str | None,
    ) -> None:
        self._shadow = shadow_base_url.rstrip("/")
        self._sar = sar_url.strip() if sar_url else None
        logger.info(
            "ai_gateway_cloud shadow_base=%s sar_gemini_proxy=%s",
            self._shadow,
            bool(self._sar),
        )

    @classmethod
    def from_environment(cls) -> CloudAIGateway:
        shadow = (
            os.environ.get("SHADOW_VLLM_BASE_URL")
            or os.environ.get("SHADOW_LLM_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        ).strip()
        sar = (os.environ.get("SAARTHI_GEMINI_URL") or "").strip() or None
        return cls(shadow_base_url=shadow, sar_url=sar)

    @property
    def shadow_investigate_base_url(self) -> str:
        return self._shadow

    @property
    def sar_llm_base_url(self) -> str | None:
        return self._sar

    async def run_shadow_investigate_inference(self, coro: Callable[[], Awaitable[T]]) -> T:
        return await coro()

    async def run_sar_inference(self, coro: Callable[[], Awaitable[T]]) -> T:
        return await coro()
