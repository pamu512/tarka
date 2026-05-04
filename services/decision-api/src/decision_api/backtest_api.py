"""Distributed backtesting: compile candidate rules to ClickHouse-safe audit SQL (PIT-aware template)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/rules/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    """ISO end time (UTC); window is [end-90d, end)."""
    end_time: datetime | None = None
    rule_pack: dict[str, Any] = Field(..., description="Compiled JSON rule pack (same shape as /v1/rules/visual/compile output rule_pack)")
    clickhouse_max_execution_seconds: int = Field(default=60, ge=5, le=600)


def _pit_window_sql(req: BacktestRequest) -> tuple[str, str, str]:
    end = req.end_time or datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")
    tenant_lit = req.tenant_id.replace("'", "''")
    # Point-in-time note: join feature snapshots versioned by ingested_at / observed_at in your warehouse.
    sql = f"""SELECT
  count() AS evaluated_rows,
  countIf(decision = 'deny') AS denies,
  countIf(decision = 'review') AS reviews,
  countIf(decision = 'allow') AS allows
FROM fraud_decisions
WHERE tenant_id = '{tenant_lit}'
  AND parseDateTimeBestEffort(created_at) >= toDateTime('{start_s}')
  AND parseDateTimeBestEffort(created_at) < toDateTime('{end_s}')
SETTINGS max_execution_time = {int(req.clickhouse_max_execution_seconds)};
-- PIT: correlate fraud_features_offline by (tenant_id, entity_id, observed_at <= decision.created_at)
-- using an ASOF JOIN in a follow-up query; kept separate to bound memory.
"""
    return sql, start_s, end_s


@router.post("/preview-sql")
async def backtest_preview_sql(
    body: BacktestRequest,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Return bounded ClickHouse SQL for ops to run in their BI cluster (PIT join documented in-field)."""
    sql, start_s, end_s = _pit_window_sql(body)
    return {
        "tenant_id": body.tenant_id,
        "window_start": start_s,
        "window_end": end_s,
        "clickhouse_sql": sql,
        "rule_pack_fingerprint": str(hash(str(body.rule_pack))),
        "pit_note": "Use ASOF JOIN on feature snapshots keyed by observed_at <= decision_time to avoid leakage.",
        "memory_guard": "Run as read-only user with max_memory_usage and max_execution_time set.",
    }


@router.post("/run")
async def backtest_run_stub(
    body: BacktestRequest,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Placeholder synchronous metrics until ClickHouse credentials are wired server-side."""
    if not body.rule_pack.get("rules"):
        raise HTTPException(status_code=400, detail="rule_pack.rules required")
    _, start_s, end_s = _pit_window_sql(body)
    return {
        "status": "stub",
        "tenant_id": body.tenant_id,
        "window_start": start_s,
        "window_end": end_s,
        "metrics": {
            "true_positive": None,
            "false_positive": None,
            "note": "Connect decision-api to ClickHouse query role and replace stub with distributed aggregation.",
        },
    }
