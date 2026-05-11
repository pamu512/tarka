"""AI routing abstraction (Ollama demo vs cloud vLLM / Gemini)."""

from shadow_agent.ai_gateway.base import AIGateway
from shadow_agent.ai_gateway.factory import build_ai_gateway

__all__ = ["AIGateway", "build_ai_gateway"]
