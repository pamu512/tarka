"""Select :class:`~shadow_agent.ai_gateway.base.AIGateway` from ``ENVIRONMENT`` / ``AI_GATEWAY_MODE``."""

from __future__ import annotations

import logging
import os

from shadow_agent.ai_gateway.base import AIGateway

logger = logging.getLogger(__name__)

_CLOUD_ENV = frozenset({"production", "prod", "staging", "stage", "cloud"})
_DEMO_MODES = frozenset({"demo", "local", "development", "dev", "laptop"})


def _normalized_environment() -> str:
    return (
        (os.environ.get("ENVIRONMENT") or os.environ.get("TARKA_ENVIRONMENT") or "local")
        .strip()
        .lower()
    )


def build_ai_gateway() -> AIGateway:
    """
    * **Demo / local** → :class:`~shadow_agent.ai_gateway.demo.DemoAIGateway` (Ollama + semaphore).
    * **Cloud** → :class:`~shadow_agent.ai_gateway.cloud.CloudAIGateway` (vLLM/Gemini URLs, no lock).

    Override with ``AI_GATEWAY_MODE=demo|cloud``.
    """
    from shadow_agent.ai_gateway.cloud import CloudAIGateway
    from shadow_agent.ai_gateway.demo import DemoAIGateway

    mode = (os.environ.get("AI_GATEWAY_MODE") or "").strip().lower()
    env = _normalized_environment()

    if mode in _DEMO_MODES:
        return DemoAIGateway.from_environment()
    if mode in _CLOUD_ENV or mode == "cloud" or (mode == "" and env in _CLOUD_ENV):
        return CloudAIGateway.from_environment()
    if mode:
        logger.warning("ai_gateway_unknown_mode mode=%r env=%r defaulting=demo", mode, env)
    return DemoAIGateway.from_environment()
