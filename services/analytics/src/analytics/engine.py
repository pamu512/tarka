"""OLAP analytics engines: ClickHouse (prod) and DuckDB (local durable file)."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

from . import queries

try:
    import duckdb
except ImportError:  # pragma: no cover — install-time dependency
    duckdb = None  # type: ignore[assignment]

try:
    from clickhouse_connect.driver.client import Client
except ImportError:  # pragma: no cover
    Client = Any  # type: ignore[misc,assignment]


@dataclass(frozen=True)
class AnalyticsQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


class BaseAnalyticsEngine(ABC):
    """Shared OLAP surface for dashboards, backtests, and sink-style batch loads.

    Warehouse-scale **rule backtests** must not call ``execute_query`` for the full window at once.
    Use :func:`analytics.historical_stream.iter_backtest_row_chunks` — keyset pages (default 10k rows)
    built via ``analytics.queries.render_backtest_stream_page_*`` — so only one page is resident
    in memory per round-trip.
    """

    @property
    @abstractmethod
    def backend(self) -> Literal["clickhouse", "duckdb"]:
        raise NotImplementedError

    @abstractmethod
    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any] | Sequence[Any] | None = None,
    ) -> AnalyticsQueryResult:
        """Run a read query already rendered for this ``backend``."""

    @abstractmethod
    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Append rows to ``table`` (engine-specific typing)."""

    def get_kpi(
        self, tenant_id: str, table: str, *, max_execution_seconds: float = 5.0
    ) -> dict[str, Any]:
        """Default KPI bundle: ``event_count`` for the tenant within ``table``."""
        if self.backend == "duckdb":
            sql = queries.render_kpi_event_count_duckdb(table)
            res = self.execute_query(sql, (tenant_id,))
        else:
            sql = queries.render_kpi_event_count_clickhouse(table, int(max_execution_seconds))
            res = self.execute_query(sql, {"tid": tenant_id})
        if not res.rows:
            raise RuntimeError("analytics KPI query returned no rows")
        return {"event_count": int(res.rows[0][0]), "table": table}


def _default_duckdb_path() -> Path:
    raw = (os.environ.get("TARKA_ANALYTICS_DUCKDB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "data" / "tarka-analytics.duckdb").resolve()


class DuckDBEngine(BaseAnalyticsEngine):
    """Durable local OLAP using an on-disk DuckDB file (survives process restarts)."""

    def __init__(self, database_path: Path) -> None:
        if duckdb is None:
            raise RuntimeError("duckdb package is not installed")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = database_path
        self._conn = duckdb.connect(str(database_path))
        self._conn.execute("PRAGMA threads=4")
        self._ensure_decisions_stub_table()

    @classmethod
    def from_env(cls) -> DuckDBEngine:
        return cls(_default_duckdb_path())

    @property
    def backend(self) -> Literal["clickhouse", "duckdb"]:
        return "duckdb"

    def _ensure_decisions_stub_table(self) -> None:
        """Minimal ``fraud_decisions`` shape for KPIs + local inserts (aligned with analytics-sink)."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fraud_decisions (
                tenant_id TEXT NOT NULL,
                entity_id TEXT,
                created_at TIMESTAMP,
                trace_id TEXT,
                decision TEXT,
                score DOUBLE,
                payload_json TEXT,
                rule_hits_json TEXT
            )
            """
        )
        try:
            self._conn.execute(
                "ALTER TABLE fraud_decisions ADD COLUMN IF NOT EXISTS rule_hits_json TEXT"
            )
        except Exception:
            pass

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any] | Sequence[Any] | None = None,
    ) -> AnalyticsQueryResult:
        if isinstance(parameters, dict):
            raise TypeError("DuckDBEngine.execute_query expects a sequence of positional binds (?)")
        params = () if parameters is None else tuple(parameters)
        cur = self._conn.execute(sql, params)
        cols = tuple(d[0] for d in (cur.description or ()))
        data = cur.fetchall()
        return AnalyticsQueryResult(columns=cols, rows=tuple(tuple(r) for r in data))

    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        plan = queries.build_insert_batch_plan(table, rows[0])
        tuples = [tuple(r[c] for c in plan.columns) for r in rows]
        self._conn.executemany(plan.duckdb_sql, tuples)

    def close(self) -> None:
        self._conn.close()


class ClickHouseEngine(BaseAnalyticsEngine):
    """Production OLAP via clickhouse_connect (sync client, thread-pooled by callers)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @property
    def client(self) -> Client:
        return self._client

    @classmethod
    def connect(
        cls,
        *,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "default",
        statement_timeout_ms: int = 5000,
    ) -> ClickHouseEngine:
        host = (host or "").strip()
        if not host:
            raise RuntimeError("ClickHouse host is empty")
        timeout_s = max(int(statement_timeout_ms) / 1000.0, 0.001)
        from clickhouse_connect import get_client

        client = get_client(
            host=host,
            port=int(port),
            username=username,
            password=password or "",
            database=database or "default",
            connect_timeout=10,
            send_receive_timeout=timeout_s,
        )
        return cls(client)

    @classmethod
    def from_env(cls) -> ClickHouseEngine:
        host = (
            os.environ.get("CLICKHOUSE_HOST") or os.environ.get("CLICKHOUSE_HOSTNAME") or ""
        ).strip()
        port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
        user = (
            os.environ.get("CLICKHOUSE_USER") or os.environ.get("CLICKHOUSE_USERNAME") or "default"
        ).strip()
        password = (os.environ.get("CLICKHOUSE_PASSWORD") or "").strip()
        database = (os.environ.get("CLICKHOUSE_DATABASE") or "default").strip()
        timeout_ms = int(os.environ.get("CLICKHOUSE_STATEMENT_TIMEOUT_MS", "5000"))
        return cls.connect(
            host=host,
            port=port,
            username=user,
            password=password,
            database=database,
            statement_timeout_ms=timeout_ms,
        )

    @property
    def backend(self) -> Literal["clickhouse", "duckdb"]:
        return "clickhouse"

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, Any] | Sequence[Any] | None = None,
    ) -> AnalyticsQueryResult:
        if parameters is not None and not isinstance(parameters, dict):
            raise TypeError("ClickHouseEngine.execute_query expects a dict of named parameters")
        params = parameters or {}
        result = self._client.query(sql, parameters=params)
        cols = tuple(str(c) for c in (result.column_names or ()))
        rows = tuple(tuple(row) for row in (result.result_rows or ()))
        return AnalyticsQueryResult(columns=cols, rows=rows)

    def insert_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        queries.validate_sql_identifier(table)
        cols = list(rows[0].keys())
        for c in cols:
            queries.validate_sql_identifier(str(c))
        column_names = [str(c) for c in cols]
        self._client.insert(table, rows, column_names=column_names)


def get_analytics_engine(
    *,
    store: str | None = None,
    clickhouse_host: str = "",
    clickhouse_port: int = 8123,
    clickhouse_user: str = "default",
    clickhouse_password: str = "",
    clickhouse_database: str = "default",
    clickhouse_statement_timeout_ms: int = 5000,
) -> BaseAnalyticsEngine | None:
    """Factory driven by ``TARKA_ANALYTICS_STORE`` (or ``store`` override).

    ``duckdb`` uses a durable on-disk database (see ``TARKA_ANALYTICS_DUCKDB_PATH``).

    For ``clickhouse``, pass connection fields explicitly (e.g. from pydantic-settings); when
    the host is empty, returns ``None`` (analytics offline).
    """
    raw = (
        (store if store is not None else os.environ.get("TARKA_ANALYTICS_STORE") or "clickhouse")
        .strip()
        .lower()
    )
    if raw in ("duck", "duckdb", "local"):
        return DuckDBEngine.from_env()
    if raw in ("clickhouse", "ch", ""):
        if not (clickhouse_host or "").strip():
            return None
        try:
            return ClickHouseEngine.connect(
                host=clickhouse_host,
                port=clickhouse_port,
                username=clickhouse_user,
                password=clickhouse_password,
                database=clickhouse_database,
                statement_timeout_ms=clickhouse_statement_timeout_ms,
            )
        except Exception:
            return None
    raise ValueError(f"unsupported TARKA_ANALYTICS_STORE={raw!r}; use 'clickhouse' or 'duckdb'")


def render_backtest_sql(
    backend: Literal["clickhouse", "duckdb"], table: str, max_execution_seconds: int
) -> str:
    """Shared backtest window SQL for both engines (callers supply binds)."""
    if backend == "duckdb":
        return queries.render_backtest_window_metrics_duckdb(table)
    return queries.render_backtest_window_metrics_clickhouse(table, max_execution_seconds)
