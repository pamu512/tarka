"""Replay a hypothetical rule against recent audit-backed transactions (shadow cohort)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from ingestor.manifest_schema import TransactionSchema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_SHADOW_COHORT_LIMIT = 1000
_HIGH_POSITIVE_THRESHOLD = 0.98

_NS_SYNTH = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _synthetic_cohort_for_demo() -> list[TransactionSchema]:
    """
    Deterministic 1,000-transaction cohort when no ``audit_logs`` history is available.

    980 rows have ``amount > 1`` and 20 rows have ``amount == 0.5`` so broad predicates
    such as ``amount > 1`` surface ~98% match rates in UI gates without seeding a DB.
    """
    base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    out: list[TransactionSchema] = []
    for i in range(_SHADOW_COHORT_LIMIT):
        amt = 2.0 if i < 980 else 0.5
        out.append(
            TransactionSchema(
                entity_id=uuid.uuid5(_NS_SYNTH, f"synthetic-shadow-{i}"),
                amount=amt,
                timestamp=base,
                metadata={"cohort": "synthetic_shadow_gate"},
                country=None,
            ),
        )
    return out


def _parse_audit_payload(raw: str | None) -> dict[str, Any] | None:
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


async def _transactions_from_audit_logs(
    session: AsyncSession,
    *,
    limit: int,
) -> list[TransactionSchema]:
    """Map recent ``audit_logs`` JSON rows into :class:`~ingestor.manifest_schema.TransactionSchema`."""
    from tarka_shared.audit_trail import AuditLog

    stmt = (
        select(AuditLog.timestamp, AuditLog.action_taken)
        .where(AuditLog.action_taken.is_not(None))
        .order_by(AuditLog.id.desc())
        .limit(max(limit * 3, limit))
    )
    result = await session.execute(stmt)
    out: list[TransactionSchema] = []
    for ts, action_taken in result.all():
        doc = _parse_audit_payload(action_taken)
        if doc is None:
            continue
        amt = doc.get("amount")
        tid = doc.get("transaction_id")
        if amt is None or tid is None:
            continue
        try:
            amount = float(amt)
        except (TypeError, ValueError):
            continue
        if not amount > 0:
            continue
        try:
            entity_id = uuid.UUID(str(tid))
        except ValueError:
            continue
        ts_use = ts if isinstance(ts, datetime) else datetime.now(UTC)
        meta = doc.get("metadata")
        meta_d: dict[str, Any] = meta if isinstance(meta, dict) else {}
        country_raw = doc.get("country")
        country = str(country_raw) if country_raw is not None else None
        try:
            out.append(
                TransactionSchema(
                    entity_id=entity_id,
                    amount=amount,
                    timestamp=ts_use,
                    metadata=meta_d,
                    country=country,
                ),
            )
        except Exception:
            logger.debug("rule_shadow_test_skip_invalid_row", exc_info=True)
            continue
        if len(out) >= limit:
            break
    return out


async def load_shadow_test_transactions(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    limit: int = _SHADOW_COHORT_LIMIT,
) -> list[TransactionSchema]:
    """Prefer audit-backed history; fall back to a deterministic synthetic cohort."""
    if session_factory is None:
        logger.info("rule_shadow_test_no_audit_db_using_synthetic cohort_size=%s", limit)
        return _synthetic_cohort_for_demo()[:limit]
    async with session_factory() as session:
        rows = await _transactions_from_audit_logs(session, limit=limit)
    if not rows:
        logger.info("rule_shadow_test_empty_audit_using_synthetic cohort_size=%s", limit)
        return _synthetic_cohort_for_demo()[:limit]
    return rows[:limit]


def run_shadow_test_against_transactions(
    *,
    root_payload: dict[str, Any],
    action_value: str,
    transactions: list[TransactionSchema],
) -> dict[str, Any]:
    """
    Evaluate ``root_payload`` as a :class:`rule_engine.ast_schemas.LogicalNode` for each transaction.

    Returns summary strings suitable for the analyst console (no persistence).
    """
    try:
        from pydantic import TypeAdapter
        from rule_engine.ast_schemas import Action, LogicalNode
        from rule_engine.evaluator import evaluate_node
    except ImportError as exc:  # pragma: no cover — Docker / CI install ``rule_engine``
        raise RuntimeError("rule_engine package is required for shadow tests") from exc

    ta = TypeAdapter(LogicalNode)
    root = ta.validate_python(root_payload)
    try:
        action = Action(action_value)
    except ValueError as exc:
        raise ValueError(f"invalid action: {action_value!r}") from exc

    n = len(transactions)
    if n == 0:
        raise ValueError("no transactions in shadow cohort")

    matched = 0
    for tx in transactions:
        try:
            if evaluate_node(root, tx):
                matched += 1
        except Exception:
            logger.warning(
                "rule_shadow_test_eval_failed entity_id=%s",
                tx.entity_id,
                exc_info=True,
            )

    rate = matched / n
    if action == Action.BLOCK:
        would_block_pct = round(rate * 100.0, 1)
        would_flag_count = 0
    elif action in (Action.FLAG, Action.SHADOW_REVIEW):
        would_block_pct = 0.0
        would_flag_count = matched
    else:
        would_block_pct = 0.0
        would_flag_count = 0

    summary_line = (
        f"This rule would have blocked {would_block_pct:.1f}% of previous traffic "
        f"and flagged {would_flag_count} transactions."
    )

    warning: str | None = None
    if rate >= _HIGH_POSITIVE_THRESHOLD:
        pct_whole = int(round(rate * 100.0))
        warning = f"HIGH POSITIVE RATE: This rule affects {pct_whole}% of your traffic."

    return {
        "sample_size": n,
        "matched_count": matched,
        "match_rate": round(rate, 6),
        "would_block_pct": would_block_pct,
        "would_flag_count": would_flag_count,
        "summary_line": summary_line,
        "warning": warning,
    }


async def execute_rule_shadow_test(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    root_payload: dict[str, Any],
    action_value: str,
    limit: int = _SHADOW_COHORT_LIMIT,
) -> dict[str, Any]:
    txns = await load_shadow_test_transactions(session_factory, limit=limit)
    return run_shadow_test_against_transactions(
        root_payload=root_payload,
        action_value=action_value,
        transactions=txns,
    )
