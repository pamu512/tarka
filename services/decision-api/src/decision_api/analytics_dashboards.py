"""Executive KPIs from the configured analytics engine (ClickHouse or DuckDB); fail closed when offline."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from analytics.dashboards import (
    dashboard_cache_key,
    fetch_dashboard_aggregates_sync,
    parse_dashboard_period,
)
from analytics.engine import BaseAnalyticsEngine
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tarka_core.cache import KeyValueCache

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.config import settings  # noqa: E402
from decision_api.deps import get_kv_cache, require_analytics_engine, run_analytics_sync  # noqa: E402

log = logging.getLogger("decision-api")

router = APIRouter(prefix="/v1/analytics/dashboards", tags=["analytics-dashboards"])

_CACHE_PREFIX = "tarka:dashboard:kpis:"
_SUMMARY_CACHE_TTL = int(os.environ.get("DASHBOARD_SUMMARY_CACHE_TTL_SECONDS", "300"))
_TTL = int(os.environ.get("DASHBOARD_KPI_CACHE_TTL_SECONDS", "300"))
_SUMMARY_MAX_EXECUTION_SECONDS = 12


def _allowed_analytics_tables() -> set[str]:
    return {t.strip() for t in settings.nl_sql_allowed_tables.split(",") if t.strip()}


def _analytics_table_qualified() -> str:
    t = settings.clickhouse_analytics_events_table.strip()
    if t not in _allowed_analytics_tables():
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_CONFIG_INVALID",
                "message": (
                    "CLICKHOUSE_ANALYTICS_EVENTS_TABLE must be listed in NL_SQL_ALLOWED_TABLES; "
                    f"allowed={sorted(_allowed_analytics_tables())}"
                ),
            },
        )
    return t


_KPI_MAX_EXECUTION_SECONDS = 5


async def _count_events_for_tenant(
    engine: BaseAnalyticsEngine, tenant_id: str, table: str
) -> int:
    def _run():
        return engine.get_kpi(
            tenant_id, table, max_execution_seconds=_KPI_MAX_EXECUTION_SECONDS
        )

    try:
        payload = await run_analytics_sync(_run)
    except Exception as e:
        msg = str(e).lower()
        log.warning("Analytics KPI query failed: %s", e)
        if (
            "unknown table" in msg
            or "does not exist" in msg
            or "doesn't exist" in msg
            or "catalog error" in msg
        ):
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "ANALYTICS_TABLE_MISSING",
                    "message": "Analytics engine rejected the KPI query (table missing or inaccessible).",
                },
            ) from e
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_ENGINE_OFFLINE",
                "message": "Analytics KPI query failed or exceeded execution budget.",
            },
        ) from e

    try:
        return int(payload["event_count"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_BAD_SCALAR",
                "message": "KPI payload missing event_count.",
            },
        ) from e


@router.get("/kpis")
async def get_dashboard_kpis(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    engine: BaseAnalyticsEngine = Depends(require_analytics_engine),
    cache: KeyValueCache = Depends(get_kv_cache),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Analyst+ (admin included); tenant binding enforced when API key maps tenants.

    Uses ``require_analytics_engine`` (503 when offline). KPI queries run via ``run_analytics_sync``.
    """
    auth = getattr(request.state, "auth_user", None)
    if (
        auth
        and auth.tenant_ids
        and "*" not in auth.tenant_ids
        and tenant_id not in auth.tenant_ids
    ):
        raise HTTPException(403, "tenant not permitted for this credential")

    table = _analytics_table_qualified()
    key = f"{_CACHE_PREFIX}{tenant_id}"

    try:
        raw = await cache.get(key)
        if raw:
            cached = json.loads(raw)
            if (
                isinstance(cached, dict)
                and cached.get("source") == engine.backend
                and "event_count" in cached
            ):
                return cached
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning("Dashboard KPI cache read failed or invalid payload: %s", e)
    except Exception as e:
        log.warning("Dashboard KPI cache read failed: %s", e)

    event_count = await _count_events_for_tenant(engine, tenant_id, table)
    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "event_count": event_count,
        "source": engine.backend,
        "table": table,
    }

    try:
        await cache.set(key, json.dumps(body), ttl_seconds=_TTL)
    except Exception as e:
        log.warning("Dashboard KPI cache write failed: %s", e)

    return body


@router.get("/summary")
async def get_dashboard_summary(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    period_start: str = Query(
        ..., description="Inclusive local calendar date (YYYY-MM-DD) in ``timezone``."
    ),
    period_end: str = Query(
        ..., description="Inclusive local calendar date (YYYY-MM-DD) in ``timezone``."
    ),
    timezone: str = Query(
        "UTC",
        max_length=128,
        description="IANA timezone for interpreting ``period_*``.",
    ),
    engine: BaseAnalyticsEngine = Depends(require_analytics_engine),
    cache: KeyValueCache = Depends(get_kv_cache),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Tenant-scoped OLAP aggregates for executive dashboards (volume, block rate, top rules, geo spikes).

    Time bounds are **half-open in UTC** after expanding ``[period_start, period_end]`` as calendar days
    in ``timezone`` (point-in-time correctness vs. ``created_at`` stored as UTC timestamps).

    Responses are cached per ``tenant_id``, period, timezone, and analytics backend to avoid hammering OLAP.
    """
    auth = getattr(request.state, "auth_user", None)
    if (
        auth
        and auth.tenant_ids
        and "*" not in auth.tenant_ids
        and tenant_id not in auth.tenant_ids
    ):
        raise HTTPException(403, "tenant not permitted for this credential")

    table = _analytics_table_qualified()
    try:
        utc_start, utc_end = parse_dashboard_period(period_start, period_end, timezone)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "BAD_DASHBOARD_WINDOW", "message": str(e)},
        ) from e

    cache_key = dashboard_cache_key(
        tenant_id, period_start, period_end, timezone, engine.backend, table=table
    )

    try:
        raw = await cache.get(cache_key)
        if raw:
            cached = json.loads(raw)
            if (
                isinstance(cached, dict)
                and cached.get("source") == engine.backend
                and cached.get("tenant_id") == tenant_id
                and cached.get("table") == table
                and "total_transaction_volume" in cached
            ):
                return cached
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning("Dashboard summary cache read failed or invalid payload: %s", e)
    except Exception as e:
        log.warning("Dashboard summary cache read failed: %s", e)

    def _run() -> dict[str, Any]:
        return fetch_dashboard_aggregates_sync(
            engine,
            table,
            tenant_id,
            utc_start,
            utc_end,
            max_execution_seconds=_SUMMARY_MAX_EXECUTION_SECONDS,
        )

    try:
        aggregates = await run_analytics_sync(_run)
    except Exception as e:
        msg = str(e).lower()
        log.warning("Dashboard summary OLAP query failed: %s", e)
        if (
            "unknown table" in msg
            or "does not exist" in msg
            or "doesn't exist" in msg
            or "catalog error" in msg
        ):
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "ANALYTICS_TABLE_MISSING",
                    "message": "Analytics engine rejected a dashboard query (table missing or inaccessible).",
                },
            ) from e
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_ENGINE_OFFLINE",
                "message": "Dashboard summary query failed or exceeded execution budget.",
            },
        ) from e

    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "table": table,
        "source": engine.backend,
        "timezone": timezone.strip() or "UTC",
        "period_start": period_start,
        "period_end": period_end,
        "utc_window_start": utc_start,
        "utc_window_end_exclusive": utc_end,
        **aggregates,
    }

    try:
        await cache.set(cache_key, json.dumps(body), ttl_seconds=_SUMMARY_CACHE_TTL)
    except Exception as e:
        log.warning("Dashboard summary cache write failed: %s", e)

    return body
