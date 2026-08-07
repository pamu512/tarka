"""Durable marketplace promo redemption events (Track B3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "coupon_code": row.coupon_code,
        "user_id": row.user_id,
        "device_id": row.device_id,
        "order_total": row.order_total,
        "currency": row.currency,
        "ip_hint": row.ip_hint,
        "display_name": row.display_name,
        "flags": list(row.flags or []),
        "trace_id": row.trace_id,
        "redeemed_at": row.redeemed_at.isoformat() if row.redeemed_at else None,
    }


async def upsert_redemption(
    session: AsyncSession,
    *,
    tenant_id: str,
    coupon_code: str,
    user_id: str,
    device_id: str | None = None,
    order_total: float | None = None,
    currency: str | None = None,
    ip_hint: str | None = None,
    display_name: str | None = None,
    flags: list[str] | None = None,
    trace_id: str | None = None,
    redeemed_at: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    from integration_ingress.models import MarketplacePromoRedemption

    tid = (tenant_id or "demo").strip() or "demo"
    code = (coupon_code or "").strip().upper()
    if not code:
        raise ValueError("coupon_code required")
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id required")

    trace = (trace_id or "").strip()[:128] or None
    row = None
    if trace:
        row = await session.scalar(
            select(MarketplacePromoRedemption).where(
                MarketplacePromoRedemption.tenant_id == tid,
                MarketplacePromoRedemption.trace_id == trace,
            )
        )

    now = redeemed_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    tag_list = list(flags or [])
    materialized = row is None

    if row is None:
        row = MarketplacePromoRedemption(
            id=uuid.uuid4(),
            tenant_id=tid,
            coupon_code=code[:64],
            user_id=uid[:256],
            device_id=(device_id or "")[:256] or None,
            order_total=float(order_total) if order_total is not None else None,
            currency=(currency or "")[:16] or None,
            ip_hint=(ip_hint or "")[:64] or None,
            display_name=(display_name or "")[:256] or None,
            flags=tag_list,
            trace_id=trace,
            redeemed_at=now,
        )
        session.add(row)
    else:
        row.coupon_code = code[:64]
        row.user_id = uid[:256]
        if device_id is not None:
            row.device_id = (device_id or "")[:256] or None
        if order_total is not None:
            row.order_total = float(order_total)
        if currency is not None:
            row.currency = (currency or "")[:16] or None
        if ip_hint is not None:
            row.ip_hint = (ip_hint or "")[:64] or None
        if display_name is not None:
            row.display_name = (display_name or "")[:256] or None
        if flags is not None:
            row.flags = tag_list
        row.redeemed_at = now

    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row), materialized


async def list_redemptions(
    session: AsyncSession,
    *,
    tenant_id: str,
    coupon_code: str,
    window_days: int = 7,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplacePromoRedemption

    tid = (tenant_id or "demo").strip() or "demo"
    code = (coupon_code or "").strip().upper()
    if not code:
        return []
    days = max(1, min(int(window_days), 90))
    cap = max(1, min(int(limit), 10000))
    since = datetime.now(UTC) - timedelta(days=days)

    rows = (
        await session.scalars(
            select(MarketplacePromoRedemption)
            .where(
                MarketplacePromoRedemption.tenant_id == tid,
                MarketplacePromoRedemption.coupon_code == code,
                MarketplacePromoRedemption.redeemed_at >= since,
            )
            .order_by(MarketplacePromoRedemption.redeemed_at.desc())
            .limit(cap),
        )
    ).all()
    return [_row_to_dict(r) for r in rows]
