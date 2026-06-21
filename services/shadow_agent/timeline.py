"""Cross-case transaction timeline derived from persisted :class:`~tarka_shared.audit_trail.AuditLog` rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from tarka_shared.audit_trail import AuditLog

# Prior blocked activity must be at least this many days before the anchor event (analyst policy).
_MIN_PRIOR_BLOCKED_AGE_DAYS = 60


class TimelineEventModel(BaseModel):
    """One point on the analyst timeline (possibly highlighted for cross-case linkage)."""

    audit_log_id: int
    transaction_id: str
    timestamp: datetime
    investigation_case_number: str = Field(
        ...,
        description="Human-visible investigation case reference from ingestion metadata.",
    )
    case_outcome: str
    amount: float | None = None
    is_fraud: bool | None = None
    device_id: str | None = None
    ip_address: str | None = None
    shadow_case_id: str = Field(
        ...,
        description="Shadow ``cases.id`` / ``audit_logs.case_id`` anchor for this audit row.",
    )
    highlight: str | None = Field(
        default=None,
        description='Set to ``"cross_case"`` when this row is a prior blocked case linked by device/IP.',
    )
    matched_via: str = Field(
        ...,
        description="How this row entered the result set: ``entity_scope``, ``device_id``, or ``ip_address``.",
    )


class TimelineResponse(BaseModel):
    """Timeline for a transaction entity, including cross-case risk callouts."""

    entity_id: str
    anchor_case_number: str | None = None
    anchor_timestamp: datetime | None = None
    events: list[TimelineEventModel]
    alerts: list[str]


def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_action_json(raw: str | None) -> dict[str, Any] | None:
    if not raw or not raw.strip() or raw.strip().upper().startswith("REJECTED"):
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _is_blocked_outcome(doc: dict[str, Any]) -> bool:
    co = str(doc.get("case_outcome") or "").strip().upper()
    return co in ("BLOCKED", "BLOCK", "DENIED", "TERMINATED", "FRAUD", "CONFIRMED_FRAUD") or (
        doc.get("is_fraud") is True
    )


def _json_device_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return func.json_extract(AuditLog.action_taken, "$.device_id")
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return doc["device_id"].astext
    raise NotImplementedError(f"timeline unsupported dialect {dialect!r}")


def _json_ip_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return func.json_extract(AuditLog.action_taken, "$.ip_address")
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return doc["ip_address"].astext
    raise NotImplementedError(f"timeline unsupported dialect {dialect!r}")


def _amount_expr(bind: Any) -> ColumnElement[Any]:
    dialect = bind.dialect.name
    if dialect == "sqlite":
        from sqlalchemy import Float

        return cast(func.json_extract(AuditLog.action_taken, "$.amount"), Float)
    if dialect == "postgresql":
        from sqlalchemy import Float
        from sqlalchemy.dialects.postgresql import JSONB

        doc = cast(AuditLog.action_taken, JSONB)
        return cast(doc["amount"].astext, Float)
    raise NotImplementedError(f"timeline unsupported dialect {dialect!r}")


@dataclass(frozen=True, slots=True)
class _Anchor:
    audit_id: int
    timestamp: datetime
    device_id: str | None
    ip_address: str | None
    investigation_case_number: str | None
    transaction_id: str


async def _load_anchor(session: AsyncSession, entity_id: str) -> _Anchor | None:
    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("AsyncSession has no bind")
    amount_expr = _amount_expr(bind)
    stmt = (
        select(AuditLog.id, AuditLog.timestamp, AuditLog.action_taken)
        .where(AuditLog.case_id == entity_id, amount_expr.is_not(None))
        .order_by(AuditLog.timestamp.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    aid, ts, raw = row
    doc = _parse_action_json(raw)
    if doc is None:
        return None
    tid = _norm_str(doc.get("transaction_id")) or entity_id
    return _Anchor(
        audit_id=int(aid),
        timestamp=ts,
        device_id=_norm_str(doc.get("device_id")),
        ip_address=_norm_str(doc.get("ip_address")),
        investigation_case_number=_norm_str(doc.get("investigation_case_number")),
        transaction_id=tid,
    )


async def _collect_audit_rows(
    session: AsyncSession,
    *,
    entity_id: str,
    anchor: _Anchor,
) -> list[tuple[int, str, datetime, str]]:
    """Return ``(id, case_id, timestamp, action_taken)`` unique rows for the timeline."""
    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("AsyncSession has no bind")
    amount_expr = _amount_expr(bind)
    base_filter = amount_expr.is_not(None)

    rows_entity = (
        await session.execute(
            select(AuditLog.id, AuditLog.case_id, AuditLog.timestamp, AuditLog.action_taken).where(
                AuditLog.case_id == entity_id,
                base_filter,
            ),
        )
    ).all()

    combined: dict[int, tuple[int, str, datetime, str]] = {
        int(r[0]): (int(r[0]), str(r[1]), r[2], str(r[3])) for r in rows_entity
    }

    if anchor.device_id:
        dev_expr = _json_device_expr(bind)
        q_dev = select(
            AuditLog.id, AuditLog.case_id, AuditLog.timestamp, AuditLog.action_taken
        ).where(
            base_filter,
            dev_expr == anchor.device_id,
        )
        for r in (await session.execute(q_dev)).all():
            combined[int(r[0])] = (int(r[0]), str(r[1]), r[2], str(r[3]))

    if anchor.ip_address:
        ip_expr = _json_ip_expr(bind)
        q_ip = select(
            AuditLog.id, AuditLog.case_id, AuditLog.timestamp, AuditLog.action_taken
        ).where(
            base_filter,
            ip_expr == anchor.ip_address,
        )
        for r in (await session.execute(q_ip)).all():
            combined[int(r[0])] = (int(r[0]), str(r[1]), r[2], str(r[3]))

    return sorted(combined.values(), key=lambda t: t[2])


def _case_num(doc: dict[str, Any]) -> str:
    raw = doc.get("investigation_case_number")
    if raw is None:
        return ""
    return str(raw).strip()


def _build_events(
    *,
    entity_id: str,
    anchor: _Anchor,
    raw_rows: list[tuple[int, str, datetime, str]],
) -> tuple[list[TimelineEventModel], list[str]]:
    anchor_case = anchor.investigation_case_number
    min_age = timedelta(days=_MIN_PRIOR_BLOCKED_AGE_DAYS)
    events: list[TimelineEventModel] = []
    alerts: list[str] = []

    for audit_id, shadow_case_id, ts, action_raw in raw_rows:
        doc = _parse_action_json(action_raw)
        if doc is None:
            continue
        tid = _norm_str(doc.get("transaction_id")) or shadow_case_id
        dev = _norm_str(doc.get("device_id"))
        ip = _norm_str(doc.get("ip_address"))
        cnum = _case_num(doc)
        outcome = str(doc.get("case_outcome") or "UNKNOWN").upper()
        amt_raw = doc.get("amount")
        try:
            amount = float(amt_raw) if amt_raw is not None else None
        except (TypeError, ValueError):
            amount = None
        fraud_raw = doc.get("is_fraud")
        is_fraud = fraud_raw if isinstance(fraud_raw, bool) else None

        matched_via = "entity_scope"
        if dev and anchor.device_id and dev == anchor.device_id:
            matched_via = "device_id"
        elif ip and anchor.ip_address and ip == anchor.ip_address:
            matched_via = "ip_address"

        highlight: str | None = None
        if matched_via in ("device_id", "ip_address"):
            other_case = cnum != (anchor_case or "")
            if anchor_case is None or cnum == "":
                other_case = shadow_case_id != entity_id
            blocked = _is_blocked_outcome(doc)
            older = ts + min_age <= anchor.timestamp
            if other_case and blocked and older:
                highlight = "cross_case"

        events.append(
            TimelineEventModel(
                audit_log_id=audit_id,
                transaction_id=tid,
                timestamp=ts,
                investigation_case_number=cnum or "—",
                case_outcome=outcome,
                amount=amount,
                is_fraud=is_fraud,
                device_id=dev,
                ip_address=ip,
                shadow_case_id=shadow_case_id,
                highlight=highlight,
                matched_via=matched_via,
            ),
        )

    for ev in events:
        if ev.highlight == "cross_case" and ev.matched_via == "device_id":
            label = ev.investigation_case_number
            msg = f"High Risk: Device ID matched blocked Case #{label}"
            if msg not in alerts:
                alerts.append(msg)
            break
    else:
        for ev in events:
            if ev.highlight == "cross_case" and ev.matched_via == "ip_address":
                msg = f"High Risk: IP address matched blocked Case #{ev.investigation_case_number}"
                if msg not in alerts:
                    alerts.append(msg)
                break

    return events, alerts


async def build_transaction_timeline(session: AsyncSession, entity_id: str) -> TimelineResponse:
    """Assemble ordered events and cross-case alerts for the given transaction UUID."""
    anchor = await _load_anchor(session, entity_id)
    if anchor is None:
        return TimelineResponse(entity_id=entity_id, events=[], alerts=[])

    raw_rows = await _collect_audit_rows(session, entity_id=entity_id, anchor=anchor)
    events, alerts = _build_events(entity_id=entity_id, anchor=anchor, raw_rows=raw_rows)
    return TimelineResponse(
        entity_id=entity_id,
        anchor_case_number=anchor.investigation_case_number,
        anchor_timestamp=anchor.timestamp,
        events=events,
        alerts=alerts,
    )
