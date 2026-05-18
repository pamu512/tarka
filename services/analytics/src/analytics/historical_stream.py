"""Keyset-paginated historical event streaming for warehouse-scale backtests.

This module implements the **exact generator contract** for moving rows from
``BaseAnalyticsEngine`` to a consumer (e.g. Rust ``tarka_rule_engine``) **without**
materialising the full window:

1. Fix ``tenant_id`` and ``[window_start, window_end)`` (ISO UTC strings).
2. Initialise ``last_created_at = None``, ``last_trace_id = None``.
3. Repeat until a page returns fewer than ``chunk_size`` rows (or zero rows):

   a. Build dialect-specific SQL via ``analytics.queries.render_backtest_stream_page_*``
      with ``has_cursor = last_created_at is not None``.
   b. ``execute_query`` for one page only (at most ``chunk_size`` rows).
   c. ``yield`` the page as ``list[dict]`` (column names aligned with the SELECT list).
   d. If the page is empty, stop. Otherwise set ``last_created_at`` / ``last_trace_id``
      from the **last row** of the page (stable ``ORDER BY created_at, trace_id``).

4. Stop when the page is empty or shorter than ``chunk_size`` (end of keyspace).

``OFFSET`` is intentionally **not** used so scans remain bounded per page for
billion-row tables (caller should ensure an appropriate physical order / projection).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from typing import Any

from analytics.engine import BaseAnalyticsEngine
from analytics import queries


def _row_dict(columns: tuple[str, ...], row: tuple[Any, ...]) -> dict[str, Any]:
    return {str(c): v for c, v in zip(columns, row, strict=True)}


def _cursor_from_last_row(row: dict[str, Any]) -> tuple[str, str]:
    """Return (created_at_iso, trace_id_str) for the next keyset predicate."""
    ca = row.get("created_at")
    if isinstance(ca, _dt.datetime):
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=_dt.timezone.utc)
        else:
            ca = ca.astimezone(_dt.timezone.utc)
        ca_s = ca.strftime("%Y-%m-%d %H:%M:%S")
    else:
        ca_s = str(ca or "")
    tid = row.get("trace_id")
    tr = "" if tid is None else str(tid)
    return ca_s, tr


def iter_backtest_row_chunks(
    engine: BaseAnalyticsEngine,
    table: str,
    tenant_id: str,
    window_start_s: str,
    window_end_s: str,
    *,
    chunk_size: int = 10_000,
    clickhouse_max_execution_seconds: int = 30,
) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of historical rows; each page has at most ``chunk_size`` dict rows."""
    tbl = queries.validate_sql_identifier(table)
    last_ca: str | None = None
    last_tr: str | None = None
    while True:
        has_cursor = last_ca is not None
        if engine.backend == "duckdb":
            sql = queries.render_backtest_stream_page_duckdb(
                tbl, chunk_size=chunk_size, has_cursor=has_cursor
            )
            binds: list[Any] = [tenant_id, window_start_s, window_end_s]
            if has_cursor:
                binds.extend([last_ca, last_ca, last_tr or ""])
            res = engine.execute_query(sql, tuple(binds))
        else:
            sql = queries.render_backtest_stream_page_clickhouse(
                tbl,
                chunk_size=chunk_size,
                has_cursor=has_cursor,
                max_execution_seconds=int(clickhouse_max_execution_seconds),
            )
            params: dict[str, Any] = {
                "tid": tenant_id,
                "start_s": window_start_s,
                "end_s": window_end_s,
            }
            if has_cursor:
                params["lca"] = last_ca or ""
                params["ltr"] = last_tr or ""
            res = engine.execute_query(sql, params)
        if not res.rows:
            return
        page = [_row_dict(res.columns, tuple(r)) for r in res.rows]
        yield page
        if len(page) < int(chunk_size):
            return
        last_ca, last_tr = _cursor_from_last_row(page[-1])


def stream_backtest_rows(
    engine: BaseAnalyticsEngine,
    table: str,
    tenant_id: str,
    window_start_s: str,
    window_end_s: str,
    *,
    chunk_size: int = 10_000,
    clickhouse_max_execution_seconds: int = 30,
) -> Iterator[dict[str, Any]]:
    """Flattening view: yield one row dict at a time (still only ``chunk_size`` rows loaded per DB round-trip)."""
    for chunk in iter_backtest_row_chunks(
        engine,
        table,
        tenant_id,
        window_start_s,
        window_end_s,
        chunk_size=chunk_size,
        clickhouse_max_execution_seconds=clickhouse_max_execution_seconds,
    ):
        yield from chunk
