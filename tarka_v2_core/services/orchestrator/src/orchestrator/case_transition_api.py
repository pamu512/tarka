"""Lifecycle case status transitions (``PUT /v1/cases/{id}/status``)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tarka_shared.audit_trail import AuditLog

from orchestrator.audit_case_worker import _ensure_shadow_case_row
from orchestrator.database import atomic_transaction
from orchestrator.graph.client import GraphClient
from orchestrator.models.cases import (
    CaseHistoryORM,
    CaseORM,
    CaseStatus,
    StateTransitionError,
    transition_status,
)
from orchestrator.label_propagation import enqueue_label_propagate_task
from orchestrator.models.normalized_labels import (
    NormalizedLabelDAO,
    ground_truth_class_for_resolved_status,
)
from orchestrator.models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxDAO
from orchestrator.workers.graph_sync import sync_resolved_fraud_case_to_graph

logger = logging.getLogger(__name__)

LIFECYCLE_STATUS_TRANSITION_SOURCE = "lifecycle_case_status_transition"

_TERMINAL_STATUSES = frozenset(
    {
        CaseStatus.RESOLVED_FRAUD,
        CaseStatus.RESOLVED_LEGIT,
        CaseStatus.RESOLVED_AUTO,
    },
)


def _fingerprint_auth_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _persist_lifecycle_status_audit_log(
    session: AsyncSession,
    *,
    shadow_case_id: str,
    lifecycle_case_id: str,
    old_status: str,
    new_status: str,
    actor_id: str,
    justification: str,
    agent_notes: str | None = None,
) -> AuditLog:
    """Append-only ``audit_logs`` row for a manual or agent-driven lifecycle transition."""
    await _ensure_shadow_case_row(session, shadow_case_id)
    payload: dict[str, str] = {
        "source": LIFECYCLE_STATUS_TRANSITION_SOURCE,
        "lifecycle_case_id": lifecycle_case_id,
        "old_status": old_status,
        "new_status": new_status,
        "actor_id": actor_id,
        "justification": justification,
    }
    log = AuditLog(
        case_id=shadow_case_id,
        action_taken=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        code_executed=None,
        agent_notes=agent_notes,
    )
    session.add(log)
    await session.flush()
    return log


def _lifecycle_case_for_update_stmt(case_id: str):
    """Build a ``SELECT`` for one ``lifecycle_cases`` row (caller adds ``FOR UPDATE`` when supported)."""
    return select(CaseORM).where(CaseORM.case_id == case_id)


async def _fetch_lifecycle_case_for_update(
    session: AsyncSession,
    *,
    case_id: str,
) -> CaseORM | None:
    """
    Load and row-lock the target lifecycle case inside the open transaction.

    Uses blocking ``SELECT … FOR UPDATE`` on PostgreSQL so concurrent analyst transitions
    and background poll-loop writers serialize on the same ``lifecycle_cases`` row.
    """
    stmt = _lifecycle_case_for_update_stmt(case_id)
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


def _shadow_retro_case_outbox_payload(
    *,
    entity_id: str,
    case_id: str,
    new_status: str,
    analyst_notes: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity_id": entity_id,
        "case_id": case_id,
        "new_status": new_status,
    }
    if analyst_notes is not None and analyst_notes.strip():
        payload["analyst_notes"] = analyst_notes.strip()
    return payload


async def _enqueue_shadow_retro_tag_for_case_resolution(
    session: AsyncSession,
    *,
    case_id: str,
    entity_id: str,
    new_status: str,
    analyst_notes: str | None,
) -> None:
    """Insert a ``SHADOW_RETRO_TAG`` outbox row in the caller's open transaction."""
    await OutboxDAO.create_task(
        session,
        event_type=OUTBOX_EVENT_SHADOW_RETRO_TAG,
        idempotency_key=f"shadow_tag_case:{case_id}:{new_status}",
        payload=_shadow_retro_case_outbox_payload(
            entity_id=entity_id,
            case_id=case_id,
            new_status=new_status,
            analyst_notes=analyst_notes,
        ),
    )


async def put_lifecycle_case_status(
    *,
    audit_session_factory: async_sessionmaker[AsyncSession] | None,
    case_id: str,
    new_status_raw: str,
    reason_code: str,
    auth_token: str,
    graph_client: GraphClient | None = None,
    agent_notes: str | None = None,
    analyst_notes: str | None = None,
) -> dict[str, Any]:
    """
    Validate state machine, append ``audit_logs``, update ``lifecycle_cases.status``, link ``case_history``.

    ``reason_code`` is required for every transition and is passed as ``reopen_reason`` when reopening
    from ``RESOLVED_*`` (see :func:`transition_status`). The auth token SHA-256 fingerprint is stored
    as ``actor_id`` on the audit payload.
    """
    if audit_session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "audit_database_unconfigured",
                "message": "Case transitions require ORCHESTRATOR_AUDIT_DATABASE_URL (or test override).",
            },
        )
    cid = (case_id or "").strip()
    if not cid or len(cid) > 64 or "\x00" in cid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_case_id", "message": "case_id must be a non-empty UUID string"},
        )
    rc = (reason_code or "").strip()
    if not rc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "missing_reason_code", "message": "reason_code must be a non-empty string"},
        )
    tok = (auth_token or "").strip()
    if not tok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "missing_auth_token", "message": "X-Auth-Token must be a non-empty string"},
        )

    try:
        new_status = CaseStatus((new_status_raw or "").strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_status", "message": str(exc)},
        ) from exc

    user_link_key: str | None = None
    actor_id = _fingerprint_auth_token(tok)
    audit_log_id: int
    notes_for_audit = analyst_notes if analyst_notes is not None else agent_notes
    async with atomic_transaction(audit_session_factory) as session:
        row = await _fetch_lifecycle_case_for_update(session, case_id=cid)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "case_not_found", "message": cid},
            )
        try:
            current = CaseStatus(str(row.status))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "corrupt_case_status", "message": str(row.status)},
            ) from exc
        try:
            next_status = transition_status(
                current,
                new_status,
                reopen_reason=rc,
            )
        except StateTransitionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "illegal_transition", "message": str(exc)},
            ) from exc

        old_s = row.status
        shadow_case_id = (row.entity_id or "").strip()
        if not shadow_case_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "missing_entity_id",
                    "message": "lifecycle case has no entity_id for audit_logs FK",
                },
            )

        audit_log = await _persist_lifecycle_status_audit_log(
            session,
            shadow_case_id=shadow_case_id,
            lifecycle_case_id=cid,
            old_status=old_s,
            new_status=next_status.value,
            actor_id=actor_id,
            justification=rc,
            agent_notes=notes_for_audit,
        )
        audit_log_id = int(audit_log.id)

        row.status = next_status.value
        user_link_key = (row.user_link_key or "").strip() or None
        hist = CaseHistoryORM(
            case_id=cid,
            audit_log_id=audit_log_id,
            from_status=old_s,
            to_status=next_status.value,
            reason_code=rc,
            auth_token_fingerprint=actor_id,
        )
        session.add(hist)
        await session.flush()
        hid = int(hist.id)

        ground_truth = ground_truth_class_for_resolved_status(next_status)
        if ground_truth is not None:
            label_row = await NormalizedLabelDAO.create_analyst_disposition(
                session,
                case_history_id=hid,
                entity_id=row.entity_id,
                ground_truth_class=ground_truth,
                reason_code=rc,
                resolved_status=next_status.value,
            )
            await enqueue_label_propagate_task(
                session,
                normalized_label_id=label_row.id,
                entity_id=row.entity_id,
                source_type=label_row.source_type,
                source_id=label_row.source_id,
                ground_truth_class=label_row.ground_truth_class,
                disposition_text=rc,
                case_history_id=hid,
                audit_log_id=audit_log_id,
            )

        if next_status in _TERMINAL_STATUSES:
            await _enqueue_shadow_retro_tag_for_case_resolution(
                session,
                case_id=cid,
                entity_id=row.entity_id,
                new_status=next_status.value,
                analyst_notes=notes_for_audit,
            )

    if (
        next_status == CaseStatus.RESOLVED_FRAUD
        and graph_client is not None
        and user_link_key
    ):
        await sync_resolved_fraud_case_to_graph(graph_client, user_link_key=user_link_key)

    logger.info(
        "lifecycle_case_status_updated case_id=%s from=%s to=%s reason_code=%s "
        "history_id=%s audit_log_id=%s",
        cid,
        old_s,
        next_status.value,
        rc,
        hid,
        audit_log_id,
    )
    return {
        "case_id": cid,
        "status": next_status.value,
        "history_row_id": hid,
        "audit_log_id": audit_log_id,
    }
