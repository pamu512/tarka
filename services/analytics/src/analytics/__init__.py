"""Pluggable analytics OLAP layer (ClickHouse production, DuckDB local)."""

from .dashboards import (
    dashboard_cache_key,
    fetch_dashboard_aggregates_sync,
    parse_dashboard_period,
)
from .engine import (
    AnalyticsQueryResult,
    BaseAnalyticsEngine,
    ClickHouseEngine,
    DuckDBEngine,
    get_analytics_engine,
    render_backtest_sql,
)
from .llm_validator import (
    AnalyticsSqlUnsafeError,
    ClickHouseSchemaRegistry,
    default_analytics_registry,
    lint_and_harden_clickhouse_llm_sql,
    validate_nl_sql_for_execution,
)
from .ml_export import (
    PitMlExportStats,
    default_local_export_path,
    pit_export_uri_for_sink,
    run_point_in_time_ml_export,
    upload_parquet_presigned_s3,
)
from .syncer import SyncWorker, SyncWorkerConfig, SyncWorkerStats, gather_with_concurrency

__all__ = [
    "PitMlExportStats",
    "AnalyticsQueryResult",
    "BaseAnalyticsEngine",
    "ClickHouseEngine",
    "DuckDBEngine",
    "default_local_export_path",
    "dashboard_cache_key",
    "fetch_dashboard_aggregates_sync",
    "get_analytics_engine",
    "parse_dashboard_period",
    "pit_export_uri_for_sink",
    "render_backtest_sql",
    "run_point_in_time_ml_export",
    "upload_parquet_presigned_s3",
    "SyncWorker",
    "SyncWorkerConfig",
    "SyncWorkerStats",
    "gather_with_concurrency",
    "AnalyticsSqlUnsafeError",
    "ClickHouseSchemaRegistry",
    "default_analytics_registry",
    "lint_and_harden_clickhouse_llm_sql",
    "validate_nl_sql_for_execution",
]
