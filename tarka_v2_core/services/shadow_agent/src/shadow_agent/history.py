"""Entity-scoped audit history projections (minimal columns per row)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from tarka_shared.audit_trail import AuditLog


@dataclass(frozen=True, slots=True)
class RecentEntityTransaction:
    """One persisted transaction snapshot derived from :class:`~tarka_shared.audit_trail.AuditLog`."""

    timestamp: datetime
    amount: float | None
    is_fraud: bool | None


def _amount_and_fraud_exprs(bind: Any) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    """Dialect-specific JSON extraction from ``AuditLog.action_taken`` (JSON text)."""
    dialect = bind.dialect.name
    if dialect == "sqlite":
        amount_e = cast(func.json_extract(AuditLog.action_taken, "$.amount"), Float)
        fraud_e = func.json_extract(AuditLog.action_taken, "$.is_fraud")
        return amount_e, fraud_e
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        amount_e = cast(func.jsonb_extract_path_text(doc, "amount"), Float)
        fraud_e = func.jsonb_extract_path_text(doc, "is_fraud")
        return amount_e, fraud_e
    raise NotImplementedError(
        f"get_recent_entity_transactions: unsupported dialect {dialect!r} "
        "(supported: sqlite, postgresql)",
    )


def _coerce_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "t", "1", "yes"):
            return True
        if lowered in ("false", "f", "0", "no"):
            return False
    return None


async def get_recent_entity_transactions(
    session: AsyncSession,
    entity_id: str,
    limit: int = 5,
) -> list[RecentEntityTransaction]:
    """
    Return recent transaction-shaped audit rows for ``entity_id`` (matched on ``audit_logs.case_id``).

    Only rows whose ``action_taken`` JSON contains an ``amount`` field are included (skips
    non-transaction audits such as ingestion reject markers).

    The query projects **only** ``timestamp``, ``amount``, and ``is_fraud`` from storage.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("AsyncSession has no bind; cannot compile JSON extractors")

    amount_expr, fraud_expr = _amount_and_fraud_exprs(bind)

    stmt = (
        select(
            AuditLog.timestamp,
            amount_expr,
            fraud_expr,
        )
        .where(
            AuditLog.case_id == entity_id,
            amount_expr.is_not(None),
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    out: list[RecentEntityTransaction] = []
    for ts, amt, fraud_raw in result.all():
        out.append(
            RecentEntityTransaction(
                timestamp=ts,
                amount=float(amt) if amt is not None else None,
                is_fraud=_coerce_bool(fraud_raw),
            ),
        )
    return out
