"""Friendly-fraud heuristics: delivery confirmation alignment from audits + same-IP order history."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ingestor.schemas import TransactionSchema
from shadow_agent.schemas import ShadowDecision
from sqlalchemy import Float, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from tarka_shared.audit_trail import AuditLog

# Successful fulfillment / capture outcomes (case-insensitive match on ``case_outcome``).
_FULFILLED_OUTCOMES: frozenset[str] = frozenset(
    {
        "delivered",
        "completed",
        "settled",
        "success",
        "fulfilled",
        "paid",
        "captured",
        "shipped",
        "closed_ok",
    },
)

_DELIVERY_HASH_KEYS: frozenset[str] = frozenset(
    {
        "delivery_confirmation_hash",
        "proof_of_delivery_hash",
        "pod_hash",
        "carrier_pod_hash",
        "disputed_delivery_confirmation_hash",
    },
)

_DELIVERY_TS_KEYS: frozenset[str] = frozenset(
    {
        "delivery_confirmation_at",
        "delivery_confirmation_timestamp",
        "pod_recorded_at",
        "pod_timestamp",
        "proof_of_delivery_at",
    },
)

_HASH_HEX_RE = re.compile(r"^[0-9a-f]{16,128}$", re.IGNORECASE)


def _norm_meta(tx: TransactionSchema) -> dict[str, Any]:
    m = tx.metadata
    return m if isinstance(m, dict) else {}


def _anchor_ip(meta: dict[str, Any]) -> str | None:
    for k in ("ip_address", "ipAddress", "ip", "graph_ip", "ingress_ip"):
        raw = meta.get(k)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return None


def _expected_delivery_hash(meta: dict[str, Any]) -> str | None:
    for k in _DELIVERY_HASH_KEYS:
        raw = meta.get(k)
        if raw is None:
            continue
        s = str(raw).strip().lower()
        if s and _HASH_HEX_RE.match(s):
            return s
    return None


def _parse_iso_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    s = str(raw).strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _iter_json_blobs(*blobs: str | None) -> list[Any]:
    out: list[Any] = []
    for b in blobs:
        if not b or not str(b).strip():
            continue
        try:
            obj = json.loads(b)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out


def _collect_delivery_pairs(obj: Any, acc: list[tuple[str, datetime | None]]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {x.lower() for x in _DELIVERY_HASH_KEYS} and isinstance(v, str):
                h = v.strip().lower()
                if h and _HASH_HEX_RE.match(h):
                    ts_val: datetime | None = None
                    for tk, tv in obj.items():
                        if str(tk).lower() in {x.lower() for x in _DELIVERY_TS_KEYS}:
                            ts_val = _parse_iso_dt(tv)
                            break
                    acc.append((h, ts_val))
            _collect_delivery_pairs(v, acc)
    elif isinstance(obj, list):
        for it in obj:
            _collect_delivery_pairs(it, acc)


def _scan_delivery_confirmations(
    *,
    dispute_ts: datetime,
    expected_hash: str | None,
    action_taken: str | None,
    code_executed: str | None,
    agent_notes: str | None,
    window: timedelta,
) -> dict[str, Any]:
    pairs: list[tuple[str, datetime | None]] = []
    for root in _iter_json_blobs(action_taken, code_executed, agent_notes):
        _collect_delivery_pairs(root, pairs)

    dispute_utc = dispute_ts.astimezone(UTC) if dispute_ts.tzinfo else dispute_ts.replace(tzinfo=UTC)
    aligned = False
    hash_seen = False
    for h, pod_ts in pairs:
        if expected_hash and h == expected_hash.lower():
            hash_seen = True
            if pod_ts is None:
                continue
            pod_utc = pod_ts.astimezone(UTC)
            if abs((pod_utc - dispute_utc).total_seconds()) <= window.total_seconds():
                aligned = True
                break

    return {
        "delivery_confirmation_hash_seen_in_audit": hash_seen,
        "delivery_confirmation_timestamp_aligned_with_dispute": aligned,
        "delivery_confirmation_pairs_found": len(pairs),
    }


def _amount_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return cast(func.json_extract(AuditLog.action_taken, "$.amount"), Float)
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return cast(doc["amount"].astext, Float)
    raise NotImplementedError(f"friendly_fraud count: unsupported dialect {dialect!r}")


def _ip_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return func.json_extract(AuditLog.action_taken, "$.ip_address")
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return doc["ip_address"].astext
    raise NotImplementedError(f"friendly_fraud count: unsupported dialect {dialect!r}")


def _outcome_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return func.lower(func.json_extract(AuditLog.action_taken, "$.case_outcome"))
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return func.lower(func.coalesce(doc["case_outcome"].astext, ""))
    raise NotImplementedError(f"friendly_fraud count: unsupported dialect {dialect!r}")


def _fraud_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return func.json_extract(AuditLog.action_taken, "$.is_fraud")
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return doc["is_fraud"].astext
    raise NotImplementedError(f"friendly_fraud count: unsupported dialect {dialect!r}")


async def count_prior_successful_orders_same_ip(
    session: AsyncSession,
    *,
    ip_address: str,
    before_timestamp: datetime,
    exclude_case_id: str | None = None,
) -> int:
    """
    Count persisted Shadow-style audit rows (``amount`` present) with the same ``ip_address``,
    ``case_outcome`` in a fulfillment set, ``is_fraud`` not true, and ``timestamp`` strictly before
    ``before_timestamp``. Used as a **friendly fraud** signal (habitual good standing from same IP).
    """
    ip = (ip_address or "").strip()
    if not ip:
        return 0
    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("AsyncSession has no bind")
    amount_e = _amount_expr(bind)
    ip_e = _ip_expr(bind)
    outcome_e = _outcome_expr(bind)
    fraud_e = _fraud_expr(bind)
    before = before_timestamp.astimezone(UTC) if before_timestamp.tzinfo else before_timestamp.replace(
        tzinfo=UTC,
    )

    fulfilled = or_(*[outcome_e == v for v in sorted(_FULFILLED_OUTCOMES)])
    not_fraud = or_(
        fraud_e.is_(None),
        func.lower(cast(fraud_e, String)) == "false",
        fraud_e == 0,
        fraud_e == "0",
        cast(fraud_e, String) == "",
    )

    stmt = select(func.count()).select_from(AuditLog).where(
        amount_e.is_not(None),
        ip_e == ip,
        AuditLog.timestamp < before,
        outcome_e.is_not(None),
        outcome_e != "",
        outcome_e != "null",
        fulfilled,
        not_fraud,
    )
    if exclude_case_id:
        stmt = stmt.where(AuditLog.case_id != exclude_case_id)

    n = (await session.execute(stmt)).scalar_one()
    return int(n or 0)


async def build_friendly_fraud_signals(
    session: AsyncSession,
    tx: TransactionSchema,
    *,
    graph_context: dict[str, Any] | None = None,
    delivery_dispute_window: timedelta = timedelta(hours=72),
) -> dict[str, Any]:
    """
    Build ``friendly_fraud_signals`` for GRAPH CONTEXT:

    * Scan recent ``AuditLog`` rows for this ``entity_id`` for delivery confirmation **hashes** and
      optional timestamps; compare to ``tx.metadata`` hash + ``tx.timestamp`` (dispute anchor).
    * Count prior successful orders from the same **IP** as in transaction metadata (cross-case).
    * If ``graph_context.prior_successful_orders_same_ip`` is set (orchestrator hint), take the
      max with the audited count so operators can inject graph-derived totals.
    """
    meta = _norm_meta(tx)
    entity_s = str(tx.entity_id)
    ip = _anchor_ip(meta)
    expected = _expected_delivery_hash(meta)

    prior_db = 0
    if ip:
        prior_db = await count_prior_successful_orders_same_ip(
            session,
            ip_address=ip,
            before_timestamp=tx.timestamp,
            exclude_case_id=None,
        )

    hint_raw = (graph_context or {}).get("prior_successful_orders_same_ip")
    try:
        prior_hint = int(hint_raw) if hint_raw is not None else 0
    except (TypeError, ValueError):
        prior_hint = 0
    prior_orders = max(prior_db, prior_hint)

    stmt = (
        select(
            AuditLog.timestamp,
            AuditLog.action_taken,
            AuditLog.code_executed,
            AuditLog.agent_notes,
        )
        .where(AuditLog.case_id == entity_s)
        .order_by(AuditLog.timestamp.desc())
        .limit(120)
    )
    rows = (await session.execute(stmt)).all()

    pairs_total = 0
    hash_seen = False
    aligned = False
    for _ts_row, at, ce, an in rows:
        part = _scan_delivery_confirmations(
            dispute_ts=tx.timestamp,
            expected_hash=expected,
            action_taken=at,
            code_executed=ce,
            agent_notes=an,
            window=delivery_dispute_window,
        )
        pairs_total += int(part.get("delivery_confirmation_pairs_found") or 0)
        hash_seen = hash_seen or bool(part.get("delivery_confirmation_hash_seen_in_audit"))
        aligned = aligned or bool(part.get("delivery_confirmation_timestamp_aligned_with_dispute"))

    delivery_scan = {
        "delivery_confirmation_hash_seen_in_audit": hash_seen,
        "delivery_confirmation_timestamp_aligned_with_dispute": aligned,
        "delivery_confirmation_pairs_found": pairs_total,
    }

    return {
        "anchor_ip_address": ip,
        "expected_delivery_confirmation_hash": expected,
        "prior_successful_orders_same_ip": prior_orders,
        "prior_successful_orders_same_ip_db": prior_db,
        "prior_successful_orders_same_ip_hint": prior_hint,
        **delivery_scan,
    }


def apply_friendly_fraud_post_rules(
    decision: ShadowDecision,
    signals: dict[str, Any] | None,
) -> ShadowDecision:
    """
    When ``prior_successful_orders_same_ip`` ≥ 10, mark the dispute as **friendly fraud** in
    ``confidence_metrics`` and ensure ``ai_reasoning`` cites **Friendly fraud** for reviewers.
    """
    if not signals:
        return decision
    try:
        prior = int(signals.get("prior_successful_orders_same_ip") or 0)
    except (TypeError, ValueError):
        prior = 0
    if prior < 10:
        return decision

    cm = dict(decision.confidence_metrics or {})
    cm["dispute_classification"] = "FRIENDLY_FRAUD"
    cm["prior_successful_orders_same_ip"] = prior
    cm["delivery_confirmation_timestamp_aligned"] = bool(
        signals.get("delivery_confirmation_timestamp_aligned_with_dispute"),
    )
    cm["delivery_confirmation_hash_seen_in_audit"] = bool(
        signals.get("delivery_confirmation_hash_seen_in_audit"),
    )

    tag = "Friendly fraud"
    air = (decision.ai_reasoning or "").strip()
    if tag.lower() not in air.lower():
        prefix = (
            f"{tag}: prior successful orders from this IP ({prior}) meet the analyst threshold "
            f"(≥10). Delivery confirmation alignment in audit: "
            f"{cm['delivery_confirmation_timestamp_aligned']}. "
        )
        air = prefix + air

    return decision.model_copy(
        update={
            "confidence_metrics": cm,
            "ai_reasoning": air[:12_000],
            "is_fraud": False,
            "risk_score": float(min(float(decision.risk_score), 25.0)),
        },
    )
