"""Durable marketplace seller integrity snapshots (Track B3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "seller_id": row.seller_id,
        "successful_deliveries": int(row.successful_deliveries or 0),
        "review_count": int(row.review_count or 0),
        "window_days": int(row.window_days or 30),
        "display_name": row.display_name,
        "store_slug": row.store_slug,
        "category": row.category,
        "avg_rating": row.avg_rating,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def upsert_seller(
    session: AsyncSession,
    *,
    tenant_id: str,
    seller_id: str,
    successful_deliveries: int,
    review_count: int,
    window_days: int = 30,
    display_name: str | None = None,
    store_slug: str | None = None,
    category: str | None = None,
    avg_rating: float | None = None,
) -> tuple[dict[str, Any], bool]:
    from integration_ingress.models import MarketplaceSellerIntegrity

    tid = (tenant_id or "demo").strip() or "demo"
    sid = (seller_id or "").strip()
    if not sid:
        raise ValueError("seller_id required")

    row = await session.scalar(
        select(MarketplaceSellerIntegrity).where(
            MarketplaceSellerIntegrity.tenant_id == tid,
            MarketplaceSellerIntegrity.seller_id == sid,
        )
    )

    days = max(7, min(int(window_days), 90))
    deliveries = max(0, int(successful_deliveries))
    reviews = max(0, int(review_count))
    now = datetime.now(UTC)
    materialized = row is None

    if row is None:
        row = MarketplaceSellerIntegrity(
            id=uuid.uuid4(),
            tenant_id=tid,
            seller_id=sid[:256],
            successful_deliveries=deliveries,
            review_count=reviews,
            window_days=days,
            display_name=(display_name or "")[:256] or None,
            store_slug=(store_slug or "")[:128] or None,
            category=(category or "")[:64] or None,
            avg_rating=float(avg_rating) if avg_rating is not None else None,
            updated_at=now,
        )
        session.add(row)
    else:
        row.successful_deliveries = deliveries
        row.review_count = reviews
        row.window_days = days
        if display_name is not None:
            row.display_name = (display_name or "")[:256] or None
        if store_slug is not None:
            row.store_slug = (store_slug or "")[:128] or None
        if category is not None:
            row.category = (category or "")[:64] or None
        if avg_rating is not None:
            row.avg_rating = float(avg_rating)
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row), materialized


async def list_sellers(
    session: AsyncSession,
    tenant_id: str,
    limit: int = 40,
) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplaceSellerIntegrity

    tid = (tenant_id or "demo").strip() or "demo"
    cap = max(1, min(int(limit), 200))

    rows = (
        await session.scalars(
            select(MarketplaceSellerIntegrity)
            .where(MarketplaceSellerIntegrity.tenant_id == tid)
            .order_by(MarketplaceSellerIntegrity.updated_at.desc())
            .limit(cap),
        )
    ).all()
    return [_row_to_dict(r) for r in rows]
