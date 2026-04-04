"""Data retention policies for PostgreSQL audit records."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from decision_api.db import engine as async_engine

log = logging.getLogger("decision-api.retention")

DEFAULT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))


async def cleanup_old_audits(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete audit records older than retention_days. Returns count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
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
