"""AI routing abstraction (Ollama demo vs cloud vLLM / Gemini)."""

from ai_gateway.base import AIGateway
from ai_gateway.factory import build_ai_gateway

__all__ = ["AIGateway", "build_ai_gateway"]
