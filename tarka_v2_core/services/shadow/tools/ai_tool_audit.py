"""Persist AI tool NATS / OSINT audit rows to ``ai_tool_logs`` (Postgres in prod, SQLite in tests)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shadow.models.ai_tool_log import AIToolLogORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


async def log_ai_tool_nats_osint(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tool_name: str,
    nats_subject: str,
    reply_inbox: str | None,
    request_payload_exact: str,
    response_payload_exact: str | None,
    error: str | None,
) -> None:
    """Insert one ``ai_tool_logs`` row; swallow DB errors so tool failures stay primary."""
    row = AIToolLogORM(
        tool_name=tool_name,
        nats_subject=nats_subject,
        reply_inbox=reply_inbox,
        request_payload_exact=request_payload_exact,
        response_payload_exact=response_payload_exact,
        error=error,
    )
    try:
        async with session_factory() as session:
            async with session.begin():
                session.add(row)
    except Exception:
        logger.exception(
            "ai_tool_log_insert_failed tool=%s subject=%s",
            tool_name,
            nats_subject,
        )
