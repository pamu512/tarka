"""Executive dashboard OLAP aggregations (ClickHouse / DuckDB) with timezone-aware windows.

All warehouse SQL is dialect-separated (no ``f``-string mixing ClickHouse vs DuckDB functions).
Identifiers are validated via :mod:`analytics.queries`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlglot
from sqlglot import exp

from analytics.engine import AnalyticsQueryResult, BaseAnalyticsEngine
from analytics.queries import (
    _backtest_window_where_clickhouse,
    _backtest_window_where_duckdb,
    _clickhouse_append_settings,
    _normalize_clickhouse_named_params,
    _table_expr,
    validate_sql_identifier,
)

_TOP_LIMIT = 100


def parse_dashboard_period(
    period_start: str, period_end: str, timezone_name: str
) -> tuple[str, str]:
    """Convert inclusive local calendar ``[period_start, period_end]`` to UTC ``[utc_start, utc_end)`` ISO strings.

    ``created_at`` in the warehouse is interpreted as **UTC**; user-visible bounds are expanded in
    ``timezone_name`` (IANA) then converted to UTC for point-in-time windowing.
    """
    tz_name = (timezone_name or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"unknown IANA timezone: {timezone_name!r}") from e
    d0 = date.fromisoformat(period_start.strip())
    d1 = date.fromisoformat(period_end.strip())
    if d1 < d0:
        raise ValueError("period_end must be on or after period_start")
    start_local = datetime.combine(d0, time.min, tzinfo=tz)
    end_exclusive_local = datetime.combine(d1 + timedelta(days=1), time.min, tzinfo=tz)
    utc_start = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    utc_end = end_exclusive_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return utc_start, utc_end


def _tz_label(tz_name: str) -> str:
    return (tz_name or "UTC").strip() or "UTC"


def _row_scalar(res: AnalyticsQueryResult) -> float:
    if not res.rows or not res.columns:
        return 0.0
    v = res.rows[0][0]
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _rows_dicts(res: AnalyticsQueryResult) -> list[dict[str, Any]]:
    cols = [str(c) for c in res.columns]
    return [dict(zip(cols, tuple(r), strict=True)) for r in res.rows]


def _render_volume_duckdb(table: str) -> str:
    tbl = _table_expr(table)
    amt = exp.Coalesce(
        expressions=[
            exp.TryCast(
                this=exp.Anonymous(
                    this="json_extract",
                    expressions=[exp.column("payload_json"), exp.Literal.string("$.amount")],
                ),
                to=exp.DataType.build("DOUBLE"),
            ),
            exp.TryCast(
                this=exp.Anonymous(
                    this="json_extract",
                    expressions=[
                        exp.column("payload_json"),
                        exp.Literal.string("$.payload.amount"),
                    ],
                ),
                to=exp.DataType.build("DOUBLE"),
            ),
            exp.Literal.number(0),
        ]
    )
    q = (
        exp.select(exp.Sum(this=amt).as_("total_volume"))
        .from_(tbl)
        .where(_backtest_window_where_duckdb(table))
    )
    return q.sql(dialect="duckdb", identify=True)


def _render_volume_clickhouse(table: str, max_execution_seconds: int) -> str:
    tbl = _table_expr(table)
    amt = sqlglot.parse_one(
        "coalesce(JSONExtractFloat(payload_json, 'amount'), JSONExtractFloat(payload_json, 'payload', 'amount'), 0.0)",
        dialect="clickhouse",
    )
    q = (
        exp.select(exp.Sum(this=amt).as_("total_volume"))
        .from_(tbl)
        .where(_backtest_window_where_clickhouse(table))
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, int(max_execution_seconds))


def _render_block_rate_duckdb(table: str) -> str:
    tbl = _table_expr(table)
    num = exp.Sum(
        this=exp.Case(
            ifs=[
                exp.If(
                    this=exp.In(
                        this=exp.column("decision"),
                        expressions=[exp.Literal.string("deny"), exp.Literal.string("review")],
                    ),
                    true=exp.Literal.number(1),
                )
            ],
            default=exp.Literal.number(0),
        )
    ).as_("blocked")
    den = exp.Count(this=exp.Star()).as_("total")
    q = exp.select(num, den).from_(tbl).where(_backtest_window_where_duckdb(table))
    return q.sql(dialect="duckdb", identify=True)


def _render_block_rate_clickhouse(table: str, max_execution_seconds: int) -> str:
    tbl = _table_expr(table)
    num = sqlglot.parse_one(
        "countIf(decision IN ('deny', 'review')) AS blocked, count() AS total",
        dialect="clickhouse",
    )
    q = (
        exp.select(num.expressions[0], num.expressions[1])
        .from_(tbl)
        .where(_backtest_window_where_clickhouse(table))
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, int(max_execution_seconds))


def _render_top_rules_duckdb(table: str) -> str:
    """Explode JSON array text with a bounded index fan-out (max 51 slots per row, ``LIMIT`` 100 on output)."""
    tbl = validate_sql_identifier(table)
    # Dialect-specific string built from validated identifier only (no user SQL fragments).
    return (
        "SELECT rule_id, COUNT(*) AS hits FROM ( "
        "SELECT TRIM(BOTH '\"' FROM CAST(json_extract(rule_hits_json, '$[' || CAST(i AS VARCHAR) || ']') AS VARCHAR)) AS rule_id "
        f'FROM "{tbl}", generate_series(0, 50) AS gs(i) '
        'WHERE "tenant_id" = ? AND CAST("created_at" AS TIMESTAMP) >= CAST(? AS TIMESTAMP) '
        'AND CAST("created_at" AS TIMESTAMP) < CAST(? AS TIMESTAMP) '
        "AND json_extract(rule_hits_json, '$[' || CAST(i AS VARCHAR) || ']') IS NOT NULL "
        ") AS exploded "
        "WHERE rule_id IS NOT NULL AND rule_id <> '' "
        "GROUP BY rule_id ORDER BY hits DESC LIMIT " + str(_TOP_LIMIT)
    )


def _render_top_rules_clickhouse(table: str, max_execution_seconds: int) -> str:
    tsql = validate_sql_identifier(table)
    body = (
        "SELECT trim(BOTH '\"' FROM arrayJoin(JSONExtractArrayRaw(coalesce(rule_hits_json, '[]')))) AS rule_id "
        f'FROM "{tsql}" '
        "WHERE tenant_id = {tid:String} "
        "AND parseDateTimeBestEffort(created_at) >= toDateTime({start_s:String}) "
        "AND parseDateTimeBestEffort(created_at) < toDateTime({end_s:String}) "
        "AND length(JSONExtractArrayRaw(coalesce(rule_hits_json, '[]'))) > 0"
    )
    outer = (
        "SELECT rule_id, count() AS hits FROM ( " + body + " ) AS exploded "
        "WHERE rule_id != '' GROUP BY rule_id ORDER BY hits DESC LIMIT " + str(_TOP_LIMIT)
    )
    return _clickhouse_append_settings(
        _normalize_clickhouse_named_params(outer), int(max_execution_seconds)
    )


def _render_geo_spikes_duckdb(table: str) -> str:
    tbl = _table_expr(table)
    risk = exp.Coalesce(
        expressions=[
            exp.TryCast(
                this=exp.Anonymous(
                    this="json_extract",
                    expressions=[
                        exp.column("payload_json"),
                        exp.Literal.string("$.impossible_travel_risk"),
                    ],
                ),
                to=exp.DataType.build("DOUBLE"),
            ),
            exp.TryCast(
                this=exp.Anonymous(
                    this="json_extract",
                    expressions=[
                        exp.column("payload_json"),
                        exp.Literal.string("$.location_meta.impossible_travel_risk"),
                    ],
                ),
                to=exp.DataType.build("DOUBLE"),
            ),
            exp.Literal.number(0.0),
        ]
    )
    q = (
        exp.select(
            exp.column("entity_id"),
            exp.Max(this=risk).as_("peak_risk"),
            exp.Count(this=exp.Star()).as_("event_count"),
        )
        .from_(tbl)
        .where(
            exp.and_(
                _backtest_window_where_duckdb(table),
                exp.Not(this=exp.Is(this=exp.column("entity_id"), expression=exp.null())),
            )
        )
        .group_by(exp.column("entity_id"))
        .having(
            exp.and_(
                exp.GTE(this=exp.Max(this=risk), expression=exp.Literal.number(0.85)),
                exp.GTE(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(2)),
            )
        )
        .order_by(
            exp.Ordered(this=exp.column("peak_risk"), desc=True),
            exp.Ordered(this=exp.column("event_count"), desc=True),
        )
        .limit(_TOP_LIMIT)
    )
    return q.sql(dialect="duckdb", identify=True)


def _render_geo_spikes_clickhouse(table: str, max_execution_seconds: int) -> str:
    tsql = validate_sql_identifier(table)
    inner = (
        "SELECT entity_id, "
        "max(coalesce(JSONExtractFloat(payload_json, 'impossible_travel_risk'), "
        "JSONExtractFloat(payload_json, 'location_meta', 'impossible_travel_risk'), 0.0)) AS peak_risk, "
        "count() AS event_count "
        f'FROM "{tsql}" '
        "WHERE tenant_id = {tid:String} "
        "AND parseDateTimeBestEffort(created_at) >= toDateTime({start_s:String}) "
        "AND parseDateTimeBestEffort(created_at) < toDateTime({end_s:String}) "
        "AND entity_id != '' "
        "GROUP BY entity_id "
        "HAVING peak_risk >= 0.85 AND event_count >= 2 "
        "ORDER BY peak_risk DESC, event_count DESC "
        f"LIMIT {int(_TOP_LIMIT)}"
    )
    return _clickhouse_append_settings(
        _normalize_clickhouse_named_params(inner), int(max_execution_seconds)
    )


def _binds_duckdb(tenant_id: str, utc_start: str, utc_end: str) -> tuple[Any, ...]:
    return (tenant_id, utc_start, utc_end)


def _binds_clickhouse(tenant_id: str, utc_start: str, utc_end: str) -> dict[str, Any]:
    return {"tid": tenant_id, "start_s": utc_start, "end_s": utc_end}


def fetch_dashboard_aggregates_sync(
    engine: BaseAnalyticsEngine,
    table: str,
    tenant_id: str,
    utc_start: str,
    utc_end: str,
    *,
    max_execution_seconds: int = 12,
) -> dict[str, Any]:
    """Run bounded OLAP queries (``LIMIT`` on ranked lists) and return a JSON-serialisable summary."""
    tbl = validate_sql_identifier(table)
    backend: Literal["clickhouse", "duckdb"] = engine.backend
    if backend == "duckdb":
        b = _binds_duckdb(tenant_id, utc_start, utc_end)
        vol = engine.execute_query(_render_volume_duckdb(tbl), b)
        br = engine.execute_query(_render_block_rate_duckdb(tbl), b)
        top = engine.execute_query(_render_top_rules_duckdb(tbl), b)
        geo = engine.execute_query(_render_geo_spikes_duckdb(tbl), b)
    else:
        p = _binds_clickhouse(tenant_id, utc_start, utc_end)
        vol = engine.execute_query(
            _render_volume_clickhouse(tbl, max_execution_seconds=max_execution_seconds), p
        )
        br = engine.execute_query(
            _render_block_rate_clickhouse(tbl, max_execution_seconds=max_execution_seconds), p
        )
        top = engine.execute_query(
            _render_top_rules_clickhouse(tbl, max_execution_seconds=max_execution_seconds), p
        )
        geo = engine.execute_query(
            _render_geo_spikes_clickhouse(tbl, max_execution_seconds=max_execution_seconds), p
        )

    total_vol = _row_scalar(vol)
    blocked = 0.0
    total = 0.0
    if br.rows and len(br.columns) >= 2:
        try:
            blocked = float(br.rows[0][0] or 0)
            total = float(br.rows[0][1] or 0)
        except (TypeError, ValueError, IndexError):
            pass
    if total <= 0:
        block_rate = 0.0
    else:
        block_rate = blocked / total
    approval_rate_pct = round(100.0 * (1.0 - block_rate), 4)
    fraud_rate_pct = round(100.0 * block_rate, 4)

    top_rules = _rows_dicts(top)
    geo_spikes = _rows_dicts(geo)

    return {
        "total_transaction_volume": total_vol,
        "block_rate": round(block_rate, 6),
        "blocked_events": int(blocked),
        "total_events": int(total),
        "approval_rate_pct": approval_rate_pct,
        "fraud_rate_pct": fraud_rate_pct,
        "top_triggered_rules": top_rules,
        "geo_velocity_spikes": geo_spikes,
        "top_lists_capped_at": _TOP_LIMIT,
    }


def dashboard_cache_key(
    tenant_id: str,
    period_start: str,
    period_end: str,
    timezone_name: str,
    backend: str,
    *,
    table: str,
) -> str:
    safe_tenant = re.sub(r"[^A-Za-z0-9_.:-]+", "_", tenant_id)[:200]
    safe_table = re.sub(r"[^A-Za-z0-9_.:-]+", "_", table)[:120]
    return (
        f"tarka:dashboard:summary:{safe_tenant}:{safe_table}:"
        f"{period_start}:{period_end}:{_tz_label(timezone_name)}:{backend}"
    )
