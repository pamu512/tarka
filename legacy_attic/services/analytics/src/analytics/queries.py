"""Dialect-safe analytics SQL via sqlglot (no raw f-strings for CH vs DuckDB differences).

Identifiers (table/column names) are validated before being embedded as AST nodes.
ClickHouse-specific session settings are appended using only validated integer literals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import sqlglot
from sqlglot import exp

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CH_PARAM_SPACING = re.compile(r"\{\s*([a-zA-Z0-9_]+)\s*:\s*([A-Za-z0-9_]+)\s*\}")


def _normalize_clickhouse_named_params(sql: str) -> str:
    """sqlglot may emit ``{name: Type}``; clickhouse_connect expects ``{name:Type}``."""
    return _CH_PARAM_SPACING.sub(r"{\1:\2}", sql)


def validate_sql_identifier(name: str) -> str:
    if not name or not _IDENTIFIER.match(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


def _table_expr(table: str) -> exp.Table:
    return exp.Table(this=exp.to_identifier(validate_sql_identifier(table)))


def _clickhouse_append_settings(sql: str, max_execution_seconds: int) -> str:
    n = int(max_execution_seconds)
    if n < 0 or n > 86_400:
        raise ValueError("max_execution_seconds out of range")
    base = sql.rstrip().rstrip(";")
    sep = " " if base else ""
    return base + sep + " SETTINGS max_execution_time = " + str(n)


def _decision_eq(d: str) -> exp.Expression:
    return exp.EQ(this=exp.column("decision"), expression=exp.Literal.string(d))


def _backtest_window_where_clickhouse(table: str) -> exp.Expression:
    tenant_eq = sqlglot.parse_one("tenant_id = {tid:String}", dialect="clickhouse")
    win = sqlglot.parse_one(
        "parseDateTimeBestEffort(created_at) >= toDateTime({start_s:String}) "
        "AND parseDateTimeBestEffort(created_at) < toDateTime({end_s:String})",
        dialect="clickhouse",
    )
    return exp.and_(tenant_eq, win)


def _backtest_window_where_duckdb(table: str) -> exp.Expression:
    tenant_ph = exp.Placeholder()
    start_ph = exp.Placeholder()
    end_ph = exp.Placeholder()
    created = exp.Cast(this=exp.column("created_at"), to=exp.DataType.build("TIMESTAMP"))
    start_ts = exp.Cast(this=start_ph, to=exp.DataType.build("TIMESTAMP"))
    end_ts = exp.Cast(this=end_ph, to=exp.DataType.build("TIMESTAMP"))
    return exp.and_(
        exp.EQ(this=exp.column("tenant_id"), expression=tenant_ph),
        exp.GTE(this=created, expression=start_ts),
        exp.LT(this=created, expression=end_ts),
    )


def render_kpi_event_count_duckdb(table: str) -> str:
    """Tenant-scoped row count for dashboard KPI (positional ``?`` bind for tenant_id)."""
    q = (
        exp.select(exp.Count(this=exp.Star()).as_("event_count"))
        .from_(_table_expr(table))
        .where(exp.EQ(this=exp.column("tenant_id"), expression=exp.Placeholder()))
    )
    return q.sql(dialect="duckdb", identify=True)


def render_kpi_event_count_clickhouse(table: str, max_execution_seconds: int) -> str:
    """ClickHouse KPI query with named parameter ``{tid:String}`` (clickhouse_connect style)."""
    tid_cond = sqlglot.parse_one("tenant_id = {tid:String}", dialect="clickhouse")
    q = (
        exp.select(exp.Count(this=exp.Star()).as_("event_count"))
        .from_(_table_expr(table))
        .where(tid_cond)
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, max_execution_seconds)


def render_backtest_window_metrics_duckdb(table: str) -> str:
    """Positional binds: tenant_id, window_start, window_end (ISO strings cast to TIMESTAMP)."""
    tbl = _table_expr(table)
    q = (
        exp.select(
            exp.Count(this=exp.Star()).as_("hit_count"),
            exp.Count(this=exp.Distinct(expressions=[exp.column("entity_id")])).as_("entity_count"),
        )
        .from_(tbl)
        .where(_backtest_window_where_duckdb(table))
    )
    return q.sql(dialect="duckdb", identify=True)


def render_backtest_pit_decision_counts_clickhouse(table: str, max_execution_seconds: int) -> str:
    """Named parameters ``tid``, ``start_s``, ``end_s`` (clickhouse_connect)."""
    where = _backtest_window_where_clickhouse(table)
    deny_if = exp.CountIf(this=_decision_eq("deny")).as_("denies")
    review_if = exp.CountIf(this=_decision_eq("review")).as_("reviews")
    allow_if = exp.CountIf(this=_decision_eq("allow")).as_("allows")
    q = (
        exp.select(
            exp.Count(this=exp.Star()).as_("evaluated_rows"),
            deny_if,
            review_if,
            allow_if,
        )
        .from_(_table_expr(table))
        .where(where)
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, max_execution_seconds)


def render_backtest_pit_decision_counts_duckdb(table: str) -> str:
    """Positional binds: tenant_id, window_start, window_end (ISO strings)."""
    where = _backtest_window_where_duckdb(table)

    def _sum_case(d: str, alias: str) -> exp.Expression:
        return exp.Sum(
            this=exp.Case(
                ifs=[exp.If(this=_decision_eq(d), true=exp.Literal.number(1))],
                default=exp.Literal.number(0),
            )
        ).as_(alias)

    q = (
        exp.select(
            exp.Count(this=exp.Star()).as_("evaluated_rows"),
            _sum_case("deny", "denies"),
            _sum_case("review", "reviews"),
            _sum_case("allow", "allows"),
        )
        .from_(_table_expr(table))
        .where(where)
    )
    return q.sql(dialect="duckdb", identify=True)


def render_backtest_window_metrics_clickhouse(table: str, max_execution_seconds: int) -> str:
    """Named parameters ``tid``, ``start_s``, ``end_s`` for clickhouse_connect."""
    tbl = _table_expr(table)
    q = (
        exp.select(
            exp.Count(this=exp.Star()).as_("hit_count"),
            exp.ApproxDistinct(this=exp.column("entity_id")).as_("entity_count"),
        )
        .from_(tbl)
        .where(_backtest_window_where_clickhouse(table))
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, max_execution_seconds)


AnalyticsBackend = Literal["clickhouse", "duckdb"]


def _clamp_chunk_size(chunk_size: int) -> int:
    n = int(chunk_size)
    if n < 1 or n > 100_000:
        raise ValueError("chunk_size must be between 1 and 100000")
    return n


def _duck_ts_col() -> exp.Expression:
    return exp.Cast(this=exp.column("created_at"), to=exp.DataType.build("TIMESTAMP"))


def _duck_trace_sort() -> exp.Expression:
    return exp.Coalesce(expressions=[exp.column("trace_id"), exp.Literal.string("")])


def _duck_keyset_predicate() -> exp.Expression:
    """``(created_at > lca) OR (created_at = lca AND coalesce(trace_id,'') > ltr)`` using positional binds."""
    ca = _duck_ts_col()
    lca = exp.Cast(this=exp.Placeholder(), to=exp.DataType.build("TIMESTAMP"))
    ltr = exp.Placeholder()
    gt_ts = exp.GT(this=ca, expression=lca)
    eq_ts = exp.EQ(this=ca, expression=lca)
    gt_tr = exp.GT(this=_duck_trace_sort(), expression=ltr)
    return exp.or_(gt_ts, exp.and_(eq_ts, gt_tr))


def render_backtest_stream_page_duckdb(
    table: str,
    *,
    chunk_size: int,
    has_cursor: bool,
) -> str:
    """Keyset-paginated historical rows for rule backtests (positional binds, ``LIMIT`` is literal only).

    Binds (positional ``?``), in order:

    - Always: ``tenant_id``, ``window_start``, ``window_end``
    - If ``has_cursor``: ``last_created_at``, ``last_created_at`` (duplicate for equality leg), ``last_trace_id``
    """
    _clamp_chunk_size(chunk_size)
    tbl = _table_expr(table)
    ca = _duck_ts_col()
    preds = [_backtest_window_where_duckdb(table)]
    if has_cursor:
        preds.append(_duck_keyset_predicate())
    where = exp.and_(*preds)
    q = (
        exp.select(
            exp.column("tenant_id"),
            exp.column("entity_id"),
            exp.column("created_at"),
            exp.column("trace_id"),
            exp.column("decision"),
            exp.column("score"),
            exp.column("payload_json"),
        )
        .from_(tbl)
        .where(where)
        .order_by(exp.Order(expressions=[ca, _duck_trace_sort()]))
        .limit(exp.Literal.number(int(chunk_size)))
    )
    return q.sql(dialect="duckdb", identify=True)


def render_backtest_stream_page_clickhouse(
    table: str, *, chunk_size: int, has_cursor: bool, max_execution_seconds: int
) -> str:
    """Keyset page over historical rows (named params for clickhouse_connect).

    Params always include ``tid``, ``start_s``, ``end_s``. When ``has_cursor``, add ``lca``, ``ltr`` (ISO strings).
    """
    _clamp_chunk_size(chunk_size)
    tbl = _table_expr(table)
    preds = [_backtest_window_where_clickhouse(table)]
    if has_cursor:
        ca = sqlglot.parse_one("parseDateTimeBestEffort(created_at)", dialect="clickhouse")
        lca = sqlglot.parse_one("toDateTime({lca:String})", dialect="clickhouse")
        gt_ts = exp.GT(this=ca, expression=lca)
        eq_ts = exp.EQ(this=ca, expression=lca)
        gt_tr = sqlglot.parse_one("coalesce(trace_id, '') > {ltr:String}", dialect="clickhouse")
        preds.append(exp.or_(gt_ts, exp.and_(eq_ts, gt_tr)))
    where = exp.and_(*preds)
    q = (
        exp.select(
            exp.column("tenant_id"),
            exp.column("entity_id"),
            exp.column("created_at"),
            exp.column("trace_id"),
            exp.column("decision"),
            exp.column("score"),
            exp.column("payload_json"),
        )
        .from_(tbl)
        .where(where)
        .order_by(
            exp.Order(
                expressions=[
                    sqlglot.parse_one("parseDateTimeBestEffort(created_at)", dialect="clickhouse"),
                    sqlglot.parse_one("coalesce(trace_id, '')", dialect="clickhouse"),
                ]
            )
        )
        .limit(exp.Literal.number(int(chunk_size)))
    )
    base = _normalize_clickhouse_named_params(q.sql(dialect="clickhouse", identify=True))
    return _clickhouse_append_settings(base, int(max_execution_seconds))


@dataclass(frozen=True)
class InsertBatchPlan:
    """Validated DuckDB INSERT … VALUES with positional placeholders."""

    table: str
    columns: tuple[str, ...]
    duckdb_sql: str


def build_insert_batch_plan(table: str, sample_row: dict[str, Any]) -> InsertBatchPlan:
    """Build a single-row INSERT template; ``executemany`` supplies bound values."""
    t = validate_sql_identifier(table)
    if not sample_row:
        raise ValueError("insert_batch requires a non-empty sample row for column list")
    cols = tuple(validate_sql_identifier(c) for c in sample_row)
    t_sql = exp.to_identifier(t).sql(dialect="duckdb", identify=True)
    col_list = ", ".join(exp.to_identifier(c).sql(dialect="duckdb", identify=True) for c in cols)
    placeholders_duck = ", ".join("?" for _ in cols)
    duck = "INSERT INTO " + t_sql + " (" + col_list + ") VALUES (" + placeholders_duck + ")"
    return InsertBatchPlan(table=t, columns=cols, duckdb_sql=duck)
