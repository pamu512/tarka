"""Chargeback-specific ingestion: link new dispute cases to the original payment ``session_id``."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ingestor.manifest_schema import TransactionSchema
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from tarka_shared.audit_trail import AuditLog

logger = logging.getLogger(__name__)


def _extract_session_id(obj: Any) -> str | None:
    """Depth-first search for the first non-empty ``session_id`` string."""
    if isinstance(obj, dict):
        sid = obj.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        md = obj.get("metadata")
        if isinstance(md, dict):
            inner = md.get("session_id")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        for v in obj.values():
            found = _extract_session_id(v)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _extract_session_id(it)
            if found:
                return found
    return None


def _parse_jsonish(raw: str | None) -> Any | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return json.loads(str(raw).strip())
    except json.JSONDecodeError:
        return None


async def resolve_linked_session_id(session: AsyncSession, original_entity_id: str) -> str | None:
    """
    Best-effort lookup: scan recent ``audit_logs`` rows mentioning *original_entity_id* and return a
    ``session_id`` found in decoded JSON (any depth).
    """
    needle = (original_entity_id or "").strip()
    if not needle:
        return None
    stmt = (
        select(AuditLog)
        .where(
            or_(
                AuditLog.action_taken.contains(needle),
                AuditLog.agent_notes.contains(needle),
                AuditLog.code_executed.contains(needle),
            )
        )
        .order_by(AuditLog.id.desc())
        .limit(120)
    )
    rows = list(await session.scalars(stmt))
    for row in rows:
        for col in (row.action_taken, row.agent_notes, row.code_executed):
            doc = _parse_jsonish(col)
            if doc is None:
                continue
            # Only trust session ids found in blobs that also reference the original transaction.
            blob = json.dumps(doc, default=str)
            if needle not in blob:
                continue
            sid = _extract_session_id(doc)
            if sid:
                return sid
    logger.info("chargeback_session_resolve_miss entity_id=%s rows_scanned=%s", needle, len(rows))
    return None


def build_chargeback_transaction(
    *,
    original_entity_id: UUID | str,
    amount: float,
    country: str | None,
    metadata: dict[str, Any],
    linked_session_id: str | None,
) -> TransactionSchema:
    """Build a new dispute envelope (fresh ``entity_id``) with chargeback linkage in ``metadata``."""
    oid = str(original_entity_id).strip()
    md: dict[str, Any] = {
        **dict(metadata),
        "ingestion_type": "CHARGEBACK",
        "original_entity_id": oid,
    }
    if linked_session_id and linked_session_id.strip():
        s = linked_session_id.strip()
        md["linked_session_id"] = s
        md["session_id"] = s
    return TransactionSchema(
        entity_id=uuid4(),
        amount=amount,
        timestamp=datetime.now(UTC),
        metadata=md,
        country=country,
    )
