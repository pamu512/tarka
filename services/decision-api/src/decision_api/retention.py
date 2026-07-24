"""Data retention policies for PostgreSQL audit records."""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from decision_api.db import engine as async_engine

log = logging.getLogger("decision-api.retention")

DEFAULT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))


def _legal_hold_active() -> bool:
    return os.environ.get("AUDIT_LEGAL_HOLD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _immutable_audits_enabled() -> bool:
    # Default on: decision audits are append-only evidence unless explicitly disabled for demos.
    raw = os.environ.get("AUDIT_IMMUTABLE", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def cleanup_old_audits(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete audit records older than retention_days. Returns count deleted.

    Skips deletion when legal hold is active or immutable audit mode is enabled (default).
    """
    if _legal_hold_active() or _immutable_audits_enabled():
        log.info(
            "Skipping audit retention cleanup (legal_hold=%s immutable=%s)",
            _legal_hold_active(),
            _immutable_audits_enabled(),
        )
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    from decision_api.models import AuditRecord

    async with async_engine.begin() as conn:
        result = await conn.execute(delete(AuditRecord).where(AuditRecord.created_at < cutoff))
        count = result.rowcount

    if count > 0:
        log.info("Deleted %d audit records older than %d days", count, retention_days)
    return count


async def retention_loop(interval_hours: int = 24) -> None:
    """Background loop that runs retention cleanup periodically."""
    while True:
        try:
            await cleanup_old_audits()
        except Exception as e:
            log.error("Retention cleanup failed: %s", e)
        await asyncio.sleep(interval_hours * 3600)
