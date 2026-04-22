from __future__ import annotations

"""
Fail-fast checks when COPILOT_PRODUCTION_MODE=true.

Operators must set API keys, analyst allowlists, and LLM credentials explicitly.
Does not replace network policies, TLS, or upstream RBAC.
"""


import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from investigation_agent.config import Settings


def runtime_readiness_errors() -> list[str]:
    """Best-effort writable probe for SQLite/RAG data dir (k8s readiness)."""
    try:
        from investigation_agent.knowledge_store import rag_db_path

        p = Path(rag_db_path()).resolve().parent
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".saarthi_write_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return ["investigation data directory not writable"]
    return []


def production_config_errors(
    settings: "Settings",
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


def raise_if_production_invalid(settings: "Settings") -> None:
    errs = production_config_errors(settings)
    if errs:
        raise RuntimeError(
            "investigation-agent: COPILOT_PRODUCTION_MODE misconfiguration — " + "; ".join(errs),
        )
