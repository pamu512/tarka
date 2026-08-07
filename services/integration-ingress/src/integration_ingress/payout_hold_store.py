"""Durable marketplace payout holds (evaluate tags + payout-delay automation)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_HOLD_DURATION_HOURS = 72
ALLOWED_STATUSES = frozenset({"held", "released", "pending"})


def _row_to_dict(row: Any, *, released_by: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "payout_id": row.payout_id,
        "entity_id": row.entity_id,
        "status": row.status,
        "hold_reason": row.hold_reason,
        "held_by": row.held_by,
        "decision_id": row.decision_id,
        "trace_id": row.trace_id,
        "tags": list(row.tags or []),
        "amount": row.amount,
        "currency": row.currency,
        "mule_score": row.mule_score,
        "held_at": row.held_at.isoformat() if row.held_at else None,
        "scheduled_release_at": (
            row.scheduled_release_at.isoformat() if row.scheduled_release_at else None
        ),
        "released_at": row.released_at.isoformat() if row.released_at else None,
    }
    if released_by is not None:
        out["released_by"] = released_by
    return out


async def upsert_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    payout_id: str,
    entity_id: str,
    status: str = "held",
    hold_reason: str | None = None,
    held_by: str | None = None,
    decision_id: str | None = None,
    trace_id: str | None = None,
    tags: list[str] | None = None,
    amount: float | None = None,
    currency: str | None = None,
    mule_score: float | None = None,
    hold_duration_hours: int | None = None,
) -> tuple[dict[str, Any], bool]:
    from integration_ingress.models import MarketplacePayoutHold

    tid = (tenant_id or "demo").strip() or "demo"
    pid = (payout_id or "").strip()
    if not pid:
        raise ValueError("payout_id required")
    eid = (entity_id or "").strip()
    if not eid:
        raise ValueError("entity_id required")
    st = (status or "held").strip().lower()
    if st not in ALLOWED_STATUSES:
        raise ValueError(f"invalid status {status!r}")

    row = await session.scalar(
        select(MarketplacePayoutHold).where(
            MarketplacePayoutHold.tenant_id == tid,
            MarketplacePayoutHold.payout_id == pid,
        )
    )

    hours = max(1, int(hold_duration_hours or DEFAULT_HOLD_DURATION_HOURS))
    now = datetime.now(UTC)
    tag_list = list(tags or [])
    prior_status = row.status if row is not None else None
    materialized = row is None or (
        st in ("held", "pending") and prior_status != st
    )

    if row is None:
        held_at = now
        scheduled_release_at = (
            held_at + timedelta(hours=hours) if st in ("held", "pending") else None
        )
        row = MarketplacePayoutHold(
            id=uuid.uuid4(),
            tenant_id=tid,
            payout_id=pid[:256],
            entity_id=eid[:256],
            status=st,
            hold_reason=(hold_reason or "")[:512] or None,
            held_by=(held_by or "")[:64] or None,
            decision_id=(decision_id or "")[:128] or None,
            trace_id=(trace_id or "")[:128] or None,
            tags=tag_list,
            amount=float(amount) if amount is not None else None,
            currency=(currency or "")[:16] or None,
            mule_score=float(mule_score) if mule_score is not None else None,
            held_at=held_at,
            scheduled_release_at=scheduled_release_at,
            released_at=None,
        )
        session.add(row)
    else:
        row.entity_id = eid[:256]
        row.status = st
        row.hold_reason = (hold_reason or row.hold_reason or "")[:512] or None
        row.held_by = (held_by or row.held_by or "")[:64] or None
        if decision_id is not None:
            row.decision_id = (decision_id or "")[:128] or None
        if trace_id is not None:
            row.trace_id = (trace_id or "")[:128] or None
        if tags is not None:
            row.tags = tag_list
        if amount is not None:
            row.amount = float(amount)
        if currency is not None:
            row.currency = (currency or "")[:16] or None
        if mule_score is not None:
            row.mule_score = float(mule_score)
        if st == "held":
            # ponytail: do not re-slide hold window on identical held refresh
            if prior_status != "held":
                row.held_at = now
                row.scheduled_release_at = now + timedelta(hours=hours)
            row.released_at = None
        elif st == "pending":
            # ponytail: do not re-slide delay window on identical pending refresh
            if prior_status != "pending":
                row.scheduled_release_at = now + timedelta(hours=hours)
            row.released_at = None
        elif st == "released":
            row.released_at = now

    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row), materialized


async def list_holds(
    session: AsyncSession,
    tenant_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplacePayoutHold

    tid = (tenant_id or "demo").strip() or "demo"
    cap = max(1, min(int(limit), 500))
    rows = (
        await session.scalars(
            select(MarketplacePayoutHold)
            .where(MarketplacePayoutHold.tenant_id == tid)
            .order_by(MarketplacePayoutHold.held_at.desc())
            .limit(cap),
        )
    ).all()
    return [_row_to_dict(r) for r in rows]


async def release_hold(
    session: AsyncSession,
    tenant_id: str,
    payout_id: str,
    *,
    released_by: str,
) -> dict[str, Any] | None:
    from integration_ingress.models import MarketplacePayoutHold

    tid = (tenant_id or "demo").strip() or "demo"
    pid = (payout_id or "").strip()
    if not pid:
        return None
    actor = (released_by or "analyst").strip()[:64] or "analyst"

    row = await session.scalar(
        select(MarketplacePayoutHold).where(
            MarketplacePayoutHold.tenant_id == tid,
            MarketplacePayoutHold.payout_id == pid,
        )
    )
    if row is None:
        return None

    now = datetime.now(UTC)
    row.status = "released"
    row.released_at = now
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row, released_by=actor)
