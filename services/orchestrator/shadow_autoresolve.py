"""Inline Shadow autonomous case resolution after orchestrator audit persistence."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from audit_case_worker import materialize_lifecycle_case_for_ingest
from case_transition_api import put_lifecycle_case_status
from graph.client import GraphClient
from shadow.hooks.resolve_case import (
    RESOLVED_AUTO_STATUS,
    build_autoresolve_agent_notes,
    build_autoresolve_reason_code,
    shadow_autoresolve_eligible,
)

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
    audit_session_factory: async_sessionmaker[AsyncSession],
    graph_client: GraphClient | None,
    audit_log_id: int,
    entity_id: str,
    metadata: dict[str, Any],
    actions: list[str],
    rule_data: dict[str, Any],
    shadow_data: dict[str, Any],
    auth_token: str | None = None,
    lifecycle_actions: list[str] | None = None,
) -> IngestAutoresolveOutcome:
    """
    After orchestrator ``AuditLog`` commit: materialize lifecycle case and transition to ``RESOLVED_AUTO``.

    Eligibility mirrors :func:`shadow.hooks.resolve_case.shadow_autoresolve_eligible`. The transition
    appends a dedicated ``audit_logs`` row (Pillar 1) via :func:`put_lifecycle_case_status`.
    """
    eligible, confidence, skip = shadow_autoresolve_eligible(shadow_data)
    if not eligible:
        return IngestAutoresolveOutcome(
            attempted=False,
            lifecycle_case_id=None,
            transition=None,
            skipped_reason=skip,
            confidence=confidence,
        )

    tok = (auth_token or resolve_autoresolve_auth_token() or "").strip()
    if not tok:
        logger.warning(
            "ingest_shadow_autoresolve_skipped missing_auth_token entity_id=%s audit_log_id=%s",
            entity_id,
            audit_log_id,
        )
        return IngestAutoresolveOutcome(
            attempted=False,
            lifecycle_case_id=None,
            transition=None,
            skipped_reason="missing_autoresolve_auth_token",
            confidence=confidence,
        )

    lifecycle_case_id: str | None
    materialize_actions = lifecycle_actions if lifecycle_actions is not None else actions
    async with audit_session_factory() as session:
        async with session.begin():
            lifecycle_case_id = await materialize_lifecycle_case_for_ingest(
                session,
                audit_log_id=audit_log_id,
                entity_id=entity_id,
                metadata=metadata,
                actions=materialize_actions,
                rule_data=rule_data,
                shadow_data=shadow_data,
            )

    if not lifecycle_case_id:
        return IngestAutoresolveOutcome(
            attempted=False,
            lifecycle_case_id=None,
            transition=None,
            skipped_reason="no_lifecycle_case_materialized",
            confidence=confidence,
        )

    reason_code = build_autoresolve_reason_code(shadow_data)
    notes = build_autoresolve_agent_notes(shadow_data, confidence=confidence)
    try:
        transition = await put_lifecycle_case_status(
            audit_session_factory=audit_session_factory,
            case_id=lifecycle_case_id,
            new_status_raw=RESOLVED_AUTO_STATUS,
            reason_code=reason_code,
            auth_token=tok,
            graph_client=graph_client,
            agent_notes=notes,
        )
    except HTTPException as exc:
        logger.warning(
            "ingest_shadow_autoresolve_transition_failed entity_id=%s lifecycle_case_id=%s "
            "audit_log_id=%s status=%s detail=%s",
            entity_id,
            lifecycle_case_id,
            audit_log_id,
            exc.status_code,
            exc.detail,
        )
        return IngestAutoresolveOutcome(
            attempted=True,
            lifecycle_case_id=lifecycle_case_id,
            transition=None,
            skipped_reason=f"transition_http_{exc.status_code}",
            confidence=confidence,
        )

    logger.info(
        "ingest_shadow_autoresolve_applied entity_id=%s lifecycle_case_id=%s audit_log_id=%s "
        "transition_audit_log_id=%s confidence=%s",
        entity_id,
        lifecycle_case_id,
        audit_log_id,
        transition.get("audit_log_id"),
        confidence,
    )
    return IngestAutoresolveOutcome(
        attempted=True,
        lifecycle_case_id=lifecycle_case_id,
        transition=transition,
        skipped_reason=None,
        confidence=confidence,
    )
