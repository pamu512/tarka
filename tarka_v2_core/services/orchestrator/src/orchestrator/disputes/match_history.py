"""
Cross-reference dispute / chargeback identifiers against ``audit_logs``.

Any token that appears in ``action_taken``, ``agent_notes``, or ``code_executed`` (substring match)
counts as a hit. When ``action_taken`` holds JSON in the ingest transaction shape (``amount``,
``transaction_id``, …), the parsed document is attached as ``DisputeAuditHit.transaction``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from tarka_shared.audit_trail import AuditLog, Case

logger = logging.getLogger(__name__)

_MAX_TOKEN_LEN = 512


def parse_transaction_like_action_taken(raw: str | None) -> dict[str, Any] | None:
    """
    Parse ``audit_logs.action_taken`` when it is JSON (e.g. transaction snapshot from ingest).

    Returns ``None`` for empty input, non-dict JSON, or strings that start with ``REJECTED`` (parity
    with :mod:`orchestrator.rule_shadow_test` cohort parsing).
    """
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.upper().startswith("REJECTED"):
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        s = (t or "").strip()
        if not s or "\x00" in s or len(s) > _MAX_TOKEN_LEN:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _token_in_audit_row(row: AuditLog, token: str) -> bool:
    parts = (row.action_taken or "", row.agent_notes or "", row.code_executed or "")
    return any(token in p for p in parts)


@dataclass(frozen=True, slots=True)
class DisputeAuditHit:
    """One ``audit_logs`` row that matched at least one search token."""

    audit_log_id: int
    case_id: str
    timestamp: datetime
    matched_tokens: tuple[str, ...]
    #: Parsed ``action_taken`` JSON when it decodes to an object; otherwise ``None``.
    transaction: dict[str, Any] | None


def _or_predicate_for_tokens(tokens: Sequence[str]) -> Any:
    clauses: list[Any] = []
    for t in tokens:
        clauses.append(AuditLog.action_taken.contains(t))
        clauses.append(AuditLog.agent_notes.contains(t))
        clauses.append(AuditLog.code_executed.contains(t))
    return or_(*clauses)


async def find_audit_log_hits_for_tokens(
    session: AsyncSession,
    tokens: Sequence[str],
    *,
    tenant_id: str | None = None,
    limit: int = 500,
) -> list[DisputeAuditHit]:
    """
    Return ``audit_logs`` rows whose text fields contain any of the given *tokens* (substring).

    *tenant_id* — when set, restrict to logs whose ``case_id`` belongs to a :class:`~tarka_shared.audit_trail.Case`
    with that tenant.

    Rows are newest-first by ``timestamp`` then ``id``. At most *limit* rows are scanned from the DB;
    each returned hit lists every *token* (among the normalized input order) that matched that row.
    """
    wanted = _normalize_tokens(tokens)
    if not wanted:
        return []

    pred = _or_predicate_for_tokens(wanted)
    if tenant_id:
        stmt = (
            select(AuditLog)
            .join(Case, Case.id == AuditLog.case_id)
            .where(Case.tenant_id == tenant_id)
            .where(pred)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .limit(limit)
        )
    else:
        stmt = select(AuditLog).where(pred).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)

    try:
        rows = list(await session.scalars(stmt))
    except Exception:
        logger.exception("find_audit_log_hits_for_tokens_query_failed")
        raise

    hits: list[DisputeAuditHit] = []
    for row in rows:
        matched = tuple(tok for tok in wanted if _token_in_audit_row(row, tok))
        if not matched:
            continue
        hits.append(
            DisputeAuditHit(
                audit_log_id=int(row.id),
                case_id=str(row.case_id),
                timestamp=row.timestamp,
                matched_tokens=matched,
                transaction=parse_transaction_like_action_taken(row.action_taken),
            ),
        )
    return hits


async def cross_reference_dispute_text(
    session: AsyncSession,
    text: str,
    *,
    tenant_id: str | None = None,
    limit: int = 500,
) -> list[DisputeAuditHit]:
    """
    Run :func:`orchestrator.utils.entity_parser.parse_entities` on *text*, then audit search.

    Convenience wrapper for chargeback / analyst paste workflows.
    """
    from orchestrator.utils.entity_parser import parse_entities

    pe = parse_entities(text)
    tokens = list(dict.fromkeys([*pe.order_ids, *pe.emails, *pe.tracking_numbers]))
    return await find_audit_log_hits_for_tokens(session, tokens, tenant_id=tenant_id, limit=limit)
