"""Inline Shadow autonomous case resolution after orchestrator audit persistence."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from shadow.hooks.resolve_case import shadow_autoresolve_eligible

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestAutoresolveOutcome:
    """Result of :func:`try_shadow_autoresolve_after_ingest`."""

    attempted: bool
    lifecycle_case_id: str | None
    transition: dict[str, Any] | None
    skipped_reason: str | None
    confidence: float | None = None


def resolve_autoresolve_auth_token() -> str | None:
    """Service token for lifecycle transitions (``X-Auth-Token`` fingerprint in audit payload)."""
    for env_key in ("ORCHESTRATOR_AUTORESOLVE_AUTH_TOKEN", "SHADOW_API_KEY"):
        tok = os.environ.get(env_key, "").strip()
        if tok:
            return tok
    return None


async def try_shadow_autoresolve_after_ingest(
    *,
    audit_session_factory: Any,
    graph_client: Any,
    audit_log_id: int,
    entity_id: str,
    metadata: dict[str, Any],
    actions: list[str],
    rule_data: dict[str, Any],
    shadow_data: dict[str, Any],
    auth_token: str | None = None,
    lifecycle_actions: list[str] | None = None,
) -> IngestAutoresolveOutcome:
    """Never auto-resolve from Shadow: deterministic policy + human approval remain authoritative."""
    _ = (
        audit_session_factory,
        graph_client,
        audit_log_id,
        entity_id,
        metadata,
        actions,
        rule_data,
        auth_token,
        lifecycle_actions,
    )
    _eligible, confidence, skip = shadow_autoresolve_eligible(shadow_data)
    logger.info(
        "ingest_shadow_autoresolve_disabled entity_id=%s audit_log_id=%s reason=%s",
        entity_id,
        audit_log_id,
        skip,
    )
    return IngestAutoresolveOutcome(
        attempted=False,
        lifecycle_case_id=None,
        transition=None,
        skipped_reason=skip or "ai_autoresolve_disabled",
        confidence=confidence,
    )
