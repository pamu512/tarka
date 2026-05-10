"""Postgres-backed SAR state machine, immutable audit log, and worker claim helpers."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import active_database_backend
from case_api.models import SarAuditLog, SarFiling

log = logging.getLogger("case_api.sar_transport")

SAR_PENDING_REVIEW = "PENDING_REVIEW"
SAR_APPROVED = "APPROVED"
SAR_SFTP_QUEUED = "SFTP_QUEUED"
SAR_TRANSMITTED = "TRANSMITTED"
SAR_ACKNOWLEDGED = "ACKNOWLEDGED"
SAR_FAILED = "FAILED"

_ALLOWED_TRANSITIONS: frozenset[tuple[str | None, str]] = frozenset(
    {
        (None, SAR_PENDING_REVIEW),
        (None, SAR_FAILED),
        (SAR_PENDING_REVIEW, SAR_APPROVED),
        (SAR_PENDING_REVIEW, SAR_FAILED),
        (SAR_APPROVED, SAR_SFTP_QUEUED),
        (SAR_APPROVED, SAR_FAILED),
        (SAR_SFTP_QUEUED, SAR_TRANSMITTED),
        (SAR_SFTP_QUEUED, SAR_FAILED),
        (SAR_TRANSMITTED, SAR_ACKNOWLEDGED),
        (SAR_TRANSMITTED, SAR_FAILED),
    }
)


def assert_allowed_transition(from_status: str | None, to_status: str) -> None:
    if (from_status, to_status) not in _ALLOWED_TRANSITIONS:
        raise ValueError(f"illegal SAR transition {from_status!r} -> {to_status!r}")


async def record_sar_intent_initial_state(
    session: AsyncSession,
    intent: SarFiling,
    *,
    actor: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append the first audit row (``from_status`` is ``NULL``) after the intent row exists."""
    if intent.status not in (SAR_PENDING_REVIEW, SAR_FAILED):
        raise ValueError(f"unexpected initial intent status: {intent.status!r}")
    await append_sar_audit_log(
        session,
        intent_id=intent.id,
        from_status=None,
        to_status=intent.status,
        actor=actor,
        detail=detail,
    )


async def append_sar_audit_log(
    session: AsyncSession,
    *,
    intent_id: uuid.UUID,
    from_status: str | None,
    to_status: str,
    actor: str | None,
    detail: dict[str, Any] | None = None,
    stack_trace: str | None = None,
) -> None:
    row = SarAuditLog(
        sar_filing_intent_id=intent_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        detail=detail or {},
        stack_trace=stack_trace,
    )
    session.add(row)


async def transition_sar_intent(
    session: AsyncSession,
    intent: SarFiling,
    *,
    to_status: str,
    actor: str,
    detail: dict[str, Any] | None = None,
    stack_trace: str | None = None,
) -> None:
    assert_allowed_transition(intent.status, to_status)
    prev = intent.status
    intent.status = to_status
    await append_sar_audit_log(
        session,
        intent_id=intent.id,
        from_status=prev,
        to_status=to_status,
        actor=actor,
        detail=detail,
        stack_trace=stack_trace,
    )


async def claim_next_sftp_queued_intent(session: AsyncSession) -> SarFiling | None:
    """Claim one ``SFTP_QUEUED`` intent using ``FOR UPDATE SKIP LOCKED`` on PostgreSQL."""
    stmt = (
        select(SarFiling)
        .where(SarFiling.status == SAR_SFTP_QUEUED)
        .order_by(SarFiling.created_at.asc())
        .limit(1)
    )
    if active_database_backend() == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    else:
        stmt = stmt.with_for_update()
    res = await session.execute(stmt)
    return res.scalar_one_or_none()
