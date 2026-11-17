"""Executive KPIs from the configured analytics engine (ClickHouse or DuckDB); fail closed when offline.

Moved from decision-api (prune plan v7 item 3.2): data-plane is the canonical analytics
front door behind nginx ``/api/analytics/``. The 503 reason codes and message bodies are
carried over verbatim from ``decision_api.analytics_dashboards``:

- ``ANALYTICS_CONFIG_INVALID``   (table not in NL_SQL_ALLOWED_TABLES)
- ``ANALYTICS_TABLE_MISSING``    (engine rejected the query: table missing/inaccessible)
- ``ANALYTICS_ENGINE_OFFLINE``   (query failed or exceeded the execution budget)
- ``ANALYTICS_BAD_SCALAR``       (KPI payload missing event_count)

Auth follows the sink model: API key + tenant binding via the app-level
``require_api_key`` dependency (the same as every other ``/v1/analytics/*`` route here).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anyio
from analytics.dashboards import (
    dashboard_cache_key,
    fetch_dashboard_aggregates_sync,
    parse_dashboard_period,
)
from analytics.engine import BaseAnalyticsEngine
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tarka_core.cache import KeyValueCache

from .config import settings

log = logging.getLogger("analytics-sink")

router = APIRouter(prefix="/v1/analytics/dashboards", tags=["analytics-dashboards"])

_CACHE_PREFIX = "tarka:dashboard:kpis:"
_SUMMARY_CACHE_TTL = int(os.environ.get("DASHBOARD_SUMMARY_CACHE_TTL_SECONDS", "300"))
_TTL = int(os.environ.get("DASHBOARD_KPI_CACHE_TTL_SECONDS", "300"))
_SUMMARY_MAX_EXECUTION_SECONDS = 12
_KPI_MAX_EXECUTION_SECONDS = 5


async def run_analytics_sync(fn):
    """Run a synchronous analytics engine call off the event loop."""
    return await anyio.to_thread.run_sync(fn)


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


def _require_analytics_engine(request: Request) -> BaseAnalyticsEngine:
    eng = getattr(request.app.state, "analytics_engine", None)
    if eng is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_ENGINE_OFFLINE",
                "message": "Analytics engine is not available for this deployment profile.",
            },
        )
    return eng


def _get_kv_cache(request: Request) -> KeyValueCache:
    cache = getattr(request.app.state, "kv_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "KV_CACHE_UNAVAILABLE",
                "message": "Application key-value cache is not initialized.",
            },
        )
    return cache


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
    tenant_id: str = Query(..., max_length=128),
    engine: BaseAnalyticsEngine = Depends(_require_analytics_engine),
    cache: KeyValueCache = Depends(_get_kv_cache),
) -> dict[str, Any]:
    """Tenant-scoped KPI event count, cached per tenant and backend.

    API key + tenant binding enforced at the app level (``require_api_key``).
    """
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
    engine: BaseAnalyticsEngine = Depends(_require_analytics_engine),
    cache: KeyValueCache = Depends(_get_kv_cache),
) -> dict[str, Any]:
    """Tenant-scoped OLAP aggregates for executive dashboards (volume, block rate, top rules, geo spikes).

    Time bounds are **half-open in UTC** after expanding ``[period_start, period_end]`` as calendar days
    in ``timezone`` (point-in-time correctness vs. ``created_at`` stored as UTC timestamps).

    Responses are cached per ``tenant_id``, period, timezone, and analytics backend to avoid hammering OLAP.
    """
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
