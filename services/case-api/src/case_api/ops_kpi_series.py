"""Time-bucketed investigation KPIs for dashboards and exports (Marble #57)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import get_session
from case_api.models import Case
from case_api.workflow import is_sla_breached_at

router = APIRouter(prefix="/v1/cases/ops", tags=["case-ops-kpi-series"])

_CLOSED = frozenset({"resolved", "closed"})
_OPENISH = frozenset({"open", "investigating"})


def median_float(values: list[float]) -> float | None:
    """Median with (a+b)/2 for even lengths; empty input returns None."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    m = n // 2
    if n % 2:
        return float(s[m])
    return float((s[m - 1] + s[m]) / 2.0)


def _parse_anchor(as_of: str | None) -> datetime:
    if not as_of or not str(as_of).strip():
        return datetime.now(timezone.utc)
    raw = str(as_of).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_time_buckets(
    *,
    granularity: Literal["daily", "weekly"],
    periods: int,
    anchor: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return ``periods`` half-open buckets ``[start, end)`` ending at the anchor day (daily) or week (weekly)."""
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    end_day = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[tuple[datetime, datetime]] = []
    if granularity == "daily":
        for k in range(periods - 1, -1, -1):
            period_start = end_day - timedelta(days=k)
            out.append((period_start, period_start + timedelta(days=1)))
        return out
    # weekly: Monday 00:00 UTC buckets
    monday = end_day - timedelta(days=end_day.weekday())
    last_week_start = monday
    for k in range(periods - 1, -1, -1):
        period_start = last_week_start - timedelta(weeks=k)
        out.append((period_start, period_start + timedelta(weeks=1)))
    return out


def _row_in_bucket(ts: datetime | None, start: datetime, end: datetime) -> bool:
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    return start <= ts < end


def build_bucket_payloads(
    cases: list[Any],
    buckets: list[tuple[datetime, datetime]],
) -> list[dict[str, Any]]:
    """Pure aggregation for tests and the HTTP handler."""
    payloads: list[dict[str, Any]] = []
    for period_start, period_end in buckets:
        as_of_end = period_end - timedelta(microseconds=1)
        created = 0
        closed_n = 0
        handling_hours: list[float] = []
        sla_breached_eod = 0

        for c in cases:
            st = (getattr(c, "status", None) or "").lower()
            pr = getattr(c, "priority", None) or "medium"
            ca = getattr(c, "created_at", None)
            ua = getattr(c, "updated_at", None)
            slo = getattr(c, "sla_hours_override", None)

            if _row_in_bucket(ca, period_start, period_end):
                created += 1

            if st in _CLOSED and _row_in_bucket(ua, period_start, period_end):
                closed_n += 1
                if ca and ua:
                    if ca.tzinfo is None:
                        ca = ca.replace(tzinfo=timezone.utc)
                    if ua.tzinfo is None:
                        ua = ua.replace(tzinfo=timezone.utc)
                    handling_hours.append(max(0.0, (ua - ca).total_seconds() / 3600.0))

            if st in _OPENISH and ca and ca < period_end:
                if is_sla_breached_at(pr, ca, sla_hours_override=slo, as_of=as_of_end):
                    sla_breached_eod += 1

        med = median_float(handling_hours)
        payloads.append(
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "cases_created": created,
                "cases_closed": closed_n,
                "median_handling_hours_closed": None if med is None else round(med, 4),
                "sla_breached_open_or_investigating_at_period_end": sla_breached_eod,
            },
        )
    return payloads


@router.get("/kpi-series")
async def kpi_series(
    tenant_id: str = Query(..., description="Tenant scope"),
    granularity: Literal["daily", "weekly"] = Query("daily", description="Bucket size for export"),
    periods: int = Query(14, ge=1, le=52, description="Number of buckets (days or ISO weeks)"),
    as_of: str | None = Query(
        None,
        description="Optional ISO-8601 anchor (UTC) for reproducible exports; defaults to now.",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Dashboard-ready KPI time series: throughput, handling-time medians, SLA snapshot per bucket."""
    anchor = _parse_anchor(as_of)
    buckets = build_time_buckets(granularity=granularity, periods=periods, anchor=anchor)
    if not buckets:
        return {
            "schema": "tarka.case_kpi_series/v1",
            "tenant_id": tenant_id,
            "granularity": granularity,
            "anchor": anchor.isoformat(),
            "buckets": [],
            "summary": {},
        }

    first = buckets[0][0]
    last = buckets[-1][1]
    result = await session.execute(select(Case).where(Case.tenant_id == tenant_id))
    merged = list(result.scalars().all())

    bucket_payloads = build_bucket_payloads(merged, buckets)
    all_handling: list[float] = []
    for c in merged:
        st = (c.status or "").lower()
        if st in _CLOSED and c.updated_at and c.created_at:
            ca, ua = c.created_at, c.updated_at
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            if ua.tzinfo is None:
                ua = ua.replace(tzinfo=timezone.utc)
            if first <= ua < last:
                all_handling.append(max(0.0, (ua - ca).total_seconds() / 3600.0))

    summary = {
        "cases_created_in_window": sum(b["cases_created"] for b in bucket_payloads),
        "cases_closed_in_window": sum(b["cases_closed"] for b in bucket_payloads),
        "median_handling_hours_closed_window": None if not all_handling else round(median_float(all_handling) or 0.0, 4),
    }

    return {
        "schema": "tarka.case_kpi_series/v1",
        "tenant_id": tenant_id,
        "granularity": granularity,
        "periods": periods,
        "anchor": anchor.isoformat(),
        "buckets": bucket_payloads,
        "summary": summary,
    }
