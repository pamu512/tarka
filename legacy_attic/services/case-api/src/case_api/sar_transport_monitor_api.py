"""Ops endpoints: SAR SFTP worker Kanban (DB-backed) and rate-limited force sync."""

from __future__ import annotations

import asyncio
import errno
import logging
import math
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import get_session
from case_api.models import SarFiling
from case_api.sar_transport import (
    SAR_ACKNOWLEDGED,
    SAR_APPROVED,
    SAR_FAILED,
    SAR_SFTP_QUEUED,
    SAR_TRANSMITTED,
)
from case_api.sar_transport_worker import SAR_TRANSPORT_RUN_SUBJECT, process_sar_transport_once

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/cases/ops/sar-transport", tags=["sar-transport-ops"])

BOARD_LIMIT = 80
FORCE_SFTP_SYNC_COOLDOWN_S = 60.0

_force_sync_lock = asyncio.Lock()
_last_force_sync_monotonic: float = 0.0


def _intent_card(row: SarFiling) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "case_id": str(row.case_id),
        "status": row.status,
        "sar_artifact_id": str(row.sar_artifact_id) if row.sar_artifact_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _fetch_column(
    session: AsyncSession,
    *,
    tenant_id: str,
    statuses: tuple[str, ...],
) -> tuple[int, list[dict[str, Any]]]:
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(SarFiling)
            .where(SarFiling.tenant_id == tenant_id, SarFiling.status.in_(statuses)),
        )
        or 0
    )
    res = await session.execute(
        select(SarFiling)
        .where(SarFiling.tenant_id == tenant_id, SarFiling.status.in_(statuses))
        .order_by(SarFiling.updated_at.desc())
        .limit(BOARD_LIMIT),
    )
    items = [_intent_card(r) for r in res.scalars().all()]
    return total, items


@router.get("/board")
async def sar_transport_board(
    tenant_id: str = Query(
        ..., min_length=1, description="Tenant scope (matches other case-ops endpoints)"
    ),
    session: AsyncSession = Depends(get_session),
):
    """Kanban columns backed by ``sar_filing_intents`` rows (no in-memory staging).

    **Column semantics** (worker pipeline — there is no separate persisted "claimed" lock):

    - **pending**: ``APPROVED`` (approved, not yet on the SFTP queue).
    - **claimed**: ``SFTP_QUEUED`` (eligible for ``process_sar_transport_once`` / SFTP upload).
    - **uploaded**: ``TRANSMITTED`` or ``ACKNOWLEDGED`` (successful transmit / ack).
    - **failed**: ``FAILED`` (non-Kanban strip; full counts + capped list).
    """
    pending_total, pending_items = await _fetch_column(
        session, tenant_id=tenant_id, statuses=(SAR_APPROVED,)
    )
    claimed_total, claimed_items = await _fetch_column(
        session, tenant_id=tenant_id, statuses=(SAR_SFTP_QUEUED,)
    )
    uploaded_total, uploaded_items = await _fetch_column(
        session,
        tenant_id=tenant_id,
        statuses=(SAR_TRANSMITTED, SAR_ACKNOWLEDGED),
    )
    failed_total, failed_items = await _fetch_column(
        session, tenant_id=tenant_id, statuses=(SAR_FAILED,)
    )

    return {
        "schema": "tarka.sar_transport_board/v1",
        "tenant_id": tenant_id,
        "status_mapping": {
            "pending_db_statuses": [SAR_APPROVED],
            "claimed_db_statuses": [SAR_SFTP_QUEUED],
            "uploaded_db_statuses": [SAR_TRANSMITTED, SAR_ACKNOWLEDGED],
            "failed_db_statuses": [SAR_FAILED],
            "note": "Row-level 'claimed' is a short-lived DB lock inside the worker, not a stored status.",
        },
        "columns": {
            "pending": {"count": pending_total, "items": pending_items},
            "claimed": {"count": claimed_total, "items": claimed_items},
            "uploaded": {"count": uploaded_total, "items": uploaded_items},
        },
        "failed": {"count": failed_total, "items": failed_items},
    }


@router.post("/force-sftp-sync")
async def force_sftp_sync(request: Request):
    """Publish a worker tick and process at most one queued intent.

    Strict **60 s** cooldown per case-api process (in addition to client debounce).

    SFTP failures that surface as timeouts or Paramiko SSH errors are mapped to HTTP 504 / 502
    with explicit exception handling (see implementation).
    """
    global _last_force_sync_monotonic

    async with _force_sync_lock:
        now = time.monotonic()
        if (
            _last_force_sync_monotonic != 0.0
            and (now - _last_force_sync_monotonic) < FORCE_SFTP_SYNC_COOLDOWN_S
        ):
            remaining = FORCE_SFTP_SYNC_COOLDOWN_S - (now - _last_force_sync_monotonic)
            retry_after = max(1, int(math.ceil(remaining)))
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "force_sftp_sync_rate_limited",
                    "message": f"Force SFTP sync is limited to once per {int(FORCE_SFTP_SYNC_COOLDOWN_S)} seconds.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        _last_force_sync_monotonic = now

    published = False
    broker = getattr(request.app.state, "message_broker", None)
    if broker is not None:
        try:
            await broker.publish(SAR_TRANSPORT_RUN_SUBJECT, b"{}")
            published = True
        except Exception as e:
            log.warning("force-sftp-sync: publish to broker failed: %s", e)

    try:
        processed_one = await process_sar_transport_once()
    except TimeoutError as exc:
        # ``socket.timeout`` is an alias of ``TimeoutError`` on supported Python versions.
        log.warning(
            "force-sftp-sync: TimeoutError/socket.timeout during process_sar_transport_once: %s",
            exc,
        )
        raise HTTPException(
            status_code=504,
            detail={"code": "sftp_timeout", "message": str(exc) or "SFTP operation timed out."},
        ) from exc
    except OSError as exc:
        # Network timeouts often surface as errno.ETIMEDOUT on connect/send paths.
        if getattr(exc, "errno", None) == errno.ETIMEDOUT:
            log.warning("force-sftp-sync: OSError ETIMEDOUT: %s", exc)
            raise HTTPException(
                status_code=504,
                detail={"code": "sftp_timeout", "message": str(exc) or "Connection timed out."},
            ) from exc
        raise
    except Exception as exc:
        try:
            import paramiko
        except ImportError:
            raise exc
        if isinstance(exc, paramiko.SSHException):
            log.warning("force-sftp-sync: paramiko.SSHException: %s", exc)
            raise HTTPException(
                status_code=502,
                detail={"code": "sftp_ssh_error", "message": str(exc) or "SFTP/SSH error."},
            ) from exc
        raise

    return {
        "ok": True,
        "published": published,
        "processed_one": bool(processed_one),
        "cooldown_seconds": int(FORCE_SFTP_SYNC_COOLDOWN_S),
    }
