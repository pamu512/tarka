"""ClickHouse DDL generation and execution for durable feature definitions (SR-01, SR-02)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from clickhouse_connect.driver.client import Client

from decision_api.deps import run_clickhouse_sync

_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")


def _require_identifier(label: str, value: str) -> str:
    v = value.strip()
    if not _IDENT.match(v):
        raise ValueError(f"{label} must match {_IDENT.pattern}")
    return v


def _mv_name_component(raw: str, label: str) -> str:
    """Sanitize tenant/name segments for MV object names (allows UUIDs and hyphens in input)."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip()).strip("_")[:100]
    if not s:
        raise ValueError(f"{label} is empty after sanitization")
    if s[0].isdigit():
        s = "t_" + s
    if not _IDENT.match(s):
        raise ValueError(f"{label} is not usable in a materialized view name")
    return s


@dataclass(frozen=True)
class FeatureMVInput:
    """Validated inputs for materialized view DDL (no raw client payloads in SQL)."""

    tenant_id: str
    name: str
    version: int
    aggregation: str
    group_by: str
    source_table: str


def _aggregation_state_expr(aggregation: str) -> str:
    a = aggregation.strip().lower()
    if a == "count":
        return "countState() AS agg_value"
    if a == "uniq":
        return "uniqExactState(trace_id) AS agg_value"
    if a == "sum":
        raise ValueError(
            "aggregation 'sum' is not supported for AggregatingMergeTree MV in this release; use 'count' or 'uniq'"
        )
    raise ValueError("aggregation must be one of: count, uniq (sum not supported)")


def generate_clickhouse_ddl(spec: FeatureMVInput) -> str:
    """Return a single CREATE MATERIALIZED VIEW IF NOT EXISTS statement (AggregatingMergeTree + agg_value)."""
    tenant_seg = _mv_name_component(spec.tenant_id, "tenant_id")
    name_seg = _mv_name_component(spec.name, "name")
    group_by = _require_identifier("group_by", spec.group_by)
    source = _require_identifier("source_table", spec.source_table)
    if spec.version < 1 or spec.version > 999:
        raise ValueError("version must be between 1 and 999")

    agg_sql = _aggregation_state_expr(spec.aggregation)
    mv_name = _require_identifier(
        "materialized_view_name",
        f"feature_{tenant_seg}_{name_seg}_v{spec.version}",
    )

    return f"""CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
ENGINE = AggregatingMergeTree()
ORDER BY (tenant_id, {group_by})
AS SELECT
  tenant_id,
  {group_by},
  {agg_sql}
FROM {source}
GROUP BY tenant_id, {group_by};
"""


def _ddl_conflict_benign(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "already exists" in msg:
        return True
    code = getattr(exc, "error_code", None)
    return bool(code is not None and int(code) == 57)


async def execute_feature_ddl(client: Client, ddl: str) -> None:
    """Execute DDL via clickhouse-connect off the event loop; idempotent on 'already exists'."""

    def _run() -> None:
        try:
            client.command(ddl)
        except Exception as exc:
            if _ddl_conflict_benign(exc):
                return
            raise

    await run_clickhouse_sync(client, _run)
