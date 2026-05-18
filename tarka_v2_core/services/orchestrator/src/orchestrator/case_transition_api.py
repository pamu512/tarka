"""Lifecycle case status transitions (``PUT /v1/cases/{id}/status``)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.graph.client import GraphClient
from orchestrator.models.cases import (
    CaseHistoryORM,
    CaseORM,
    CaseStatus,
    StateTransitionError,
    transition_status,
)
from orchestrator.workers.graph_sync import sync_resolved_fraud_case_to_graph

logger = logging.getLogger(__name__)


def _fingerprint_auth_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def put_lifecycle_case_status(
    *,
    audit_session_factory: async_sessionmaker[AsyncSession] | None,
    case_id: str,
    new_status_raw: str,
    reason_code: str,
    auth_token: str,
    graph_client: GraphClient | None = None,
) -> dict[str, Any]:
    """
    Validate state machine, update ``lifecycle_cases.status``, append ``case_history`` audit row.

    ``reason_code`` is required for every transition and is passed as ``reopen_reason`` when reopening
    from ``RESOLVED_*`` (see :func:`transition_status`).
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
    async with audit_session_factory() as session:
        async with session.begin():
            row = await session.scalar(select(CaseORM).where(CaseORM.case_id == cid))
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
            row.status = next_status.value
            user_link_key = (row.user_link_key or "").strip() or None
            hist = CaseHistoryORM(
                case_id=cid,
                audit_log_id=None,
                from_status=old_s,
                to_status=next_status.value,
                reason_code=rc,
                auth_token_fingerprint=_fingerprint_auth_token(tok),
            )
            session.add(hist)
            await session.flush()
            hid = int(hist.id)

    if (
        next_status == CaseStatus.RESOLVED_FRAUD
        and graph_client is not None
        and user_link_key
    ):
        await sync_resolved_fraud_case_to_graph(graph_client, user_link_key=user_link_key)

    logger.info(
        "lifecycle_case_status_updated case_id=%s from=%s to=%s reason_code=%s history_id=%s",
        cid,
        old_s,
        next_status.value,
        rc,
        hid,
    )
    return {
        "case_id": cid,
        "status": next_status.value,
        "history_row_id": hid,
    }
