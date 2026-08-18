from __future__ import annotations

import os
from typing import TYPE_CHECKING

from investigation_agent import knowledge_store

"""
Fail-fast checks when COPILOT_PRODUCTION_MODE=true.

Operators must set API keys, analyst allowlists, and LLM credentials explicitly.
Does not replace network policies, TLS, or upstream RBAC.
"""
if TYPE_CHECKING:
    from investigation_agent.config import Settings


def runtime_readiness_errors() -> list[str]:
    """Best-effort RAG store probe for k8s readiness."""
    ok, detail = knowledge_store.rag_health_check()
    if not ok:
        return [f"rag store unavailable: {detail}"]
    return []


def production_config_errors(
    settings: Settings,
    *,
    api_keys_raw: str | None = None,
) -> list[str]:
    """Return human-readable configuration errors; empty if OK or not in production mode."""
    if not settings.copilot_production_mode:
        return []
    errs: list[str] = []
    if not settings.copilot_require_investigation_api_key:
        errs.append("set COPILOT_REQUIRE_INVESTIGATION_API_KEY=true")
    if not settings.copilot_trusted_scope_headers_required:
        errs.append("set COPILOT_TRUSTED_SCOPE_HEADERS_REQUIRED=true")
    raw = (api_keys_raw if api_keys_raw is not None else os.environ.get("API_KEYS", "")).strip()
    if not raw:
        errs.append("set non-empty API_KEYS (comma-separated)")
    if (settings.allowed_analysts or "").strip() == "*":
        errs.append("set ALLOWED_ANALYSTS to explicit analyst ids (not *)")
    if not (settings.openai_api_key or "").strip():
        errs.append("set OPENAI_API_KEY (or compatible) for chat/embeddings")
    return errs


def raise_if_production_invalid(settings: Settings) -> None:
    errs = production_config_errors(settings)
    if errs:
        raise RuntimeError(
            "investigation-agent: COPILOT_PRODUCTION_MODE misconfiguration — " + "; ".join(errs),
        )
