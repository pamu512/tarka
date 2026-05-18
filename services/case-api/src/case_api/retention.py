"""Data retention policies for closed investigation cases."""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from case_api.db import engine as async_engine

log = logging.getLogger("case-api.retention")

DEFAULT_RETENTION_DAYS = int(os.environ.get("CASE_RETENTION_DAYS", "730"))


async def cleanup_old_cases(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete closed cases older than retention_days. Returns count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    from case_api.models import Case

    async with async_engine.begin() as conn:
        result = await conn.execute(
            delete(Case).where(Case.status == "closed", Case.updated_at < cutoff)
        )
        count = result.rowcount

    if count > 0:
        log.info("Deleted %d closed cases older than %d days", count, retention_days)
    return count


async def retention_loop(interval_hours: int = 24) -> None:
    """Background loop that runs retention cleanup periodically."""
    while True:
        try:
            await cleanup_old_cases()
        except Exception as e:
            log.error("Case retention cleanup failed: %s", e)
        await asyncio.sleep(interval_hours * 3600)
