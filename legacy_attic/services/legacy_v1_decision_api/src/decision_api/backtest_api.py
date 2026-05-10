"""Warehouse rule backtests: dialect-safe SQL preview + streaming OLAP jobs (ClickHouse/DuckDB → Rust → Postgres)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Self

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from analytics import queries  # noqa: E402
from analytics.engine import BaseAnalyticsEngine  # noqa: E402

from decision_api.backtest_job_runner import (  # noqa: E402
    rule_pack_fingerprint_sha256,
    run_backtest_job,
)
from decision_api.config import settings  # noqa: E402
from decision_api.db import get_session  # noqa: E402
from decision_api.deps import require_analytics_engine  # noqa: E402
from decision_api.models import BacktestRun, BacktestRunStatus  # noqa: E402

router = APIRouter(prefix="/v1/rules/backtest", tags=["backtest"])

_MAX_BACKTEST_WINDOW = timedelta(days=90)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class BacktestRequest(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    """When ``start_time`` is omitted, window is ``[end_time - 90d, end_time)`` in UTC (legacy behavior)."""
    start_time: datetime | None = None
    end_time: datetime | None = None
    rule_pack: dict[str, Any] = Field(
        ...,
        description="Compiled JSON rule pack (same shape as /v1/rules/visual/compile output rule_pack).",
    )
    clickhouse_max_execution_seconds: int = Field(default=60, ge=5, le=600)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.start_time is None:
            return self
        if self.end_time is None:
            raise ValueError("end_time is required when start_time is set")
        st = _ensure_utc(self.start_time)
        en = _ensure_utc(self.end_time)
        if en <= st:
            raise ValueError("end_time must be after start_time")
        if (en - st) > _MAX_BACKTEST_WINDOW:
            raise ValueError("backtest window must not exceed 90 days")
        return self


def _window_bounds(req: BacktestRequest) -> tuple[str, str]:
    end = req.end_time or datetime.now(timezone.utc)
    end = _ensure_utc(end)
    if req.start_time is None:
        start = end - _MAX_BACKTEST_WINDOW
    else:
        start = _ensure_utc(req.start_time)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


@router.post("/preview-sql")
async def backtest_preview_sql(
    body: BacktestRequest,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Return dialect-specific parameterized SQL for ops (binds documented below)."""
    start_s, end_s = _window_bounds(body)
    table = queries.validate_sql_identifier(
        settings.clickhouse_analytics_events_table.strip()
    )
    max_sec = max(5, min(int(body.clickhouse_max_execution_seconds), 600))
    ch_sql = queries.render_backtest_pit_decision_counts_clickhouse(table, max_sec)
    duck_sql = queries.render_backtest_pit_decision_counts_duckdb(table)
    return {
        "tenant_id": body.tenant_id,
        "window_start": start_s,
        "window_end": end_s,
        "clickhouse_sql": ch_sql,
        "duckdb_sql": duck_sql,
        "binds": {
            "clickhouse_named": {
                "tid": body.tenant_id,
                "start_s": start_s,
                "end_s": end_s,
            },
            "duckdb_positional": [body.tenant_id, start_s, end_s],
        },
        "rule_pack_fingerprint_sha256": rule_pack_fingerprint_sha256(body.rule_pack),
        "pit_note": "Use ASOF JOIN on feature snapshots keyed by observed_at <= decision_time to avoid leakage.",
        "memory_guard": "Run as read-only user with max_memory_usage and max_execution_time set.",
    }


@router.post("/jobs", status_code=202)
async def enqueue_backtest_job(
    body: BacktestRequest,
    background_tasks: BackgroundTasks,
    engine: BaseAnalyticsEngine = Depends(require_analytics_engine),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Start a streaming backtest (10k row keyset pages → Rust rule engine → Postgres aggregates)."""
    if not body.rule_pack.get("rules"):
        raise HTTPException(status_code=400, detail="rule_pack.rules required")
    start_s, end_s = _window_bounds(body)
    table = queries.validate_sql_identifier(
        settings.clickhouse_analytics_events_table.strip()
    )
    fp = rule_pack_fingerprint_sha256(body.rule_pack)
    job = BacktestRun(
        tenant_id=body.tenant_id,
        status=BacktestRunStatus.pending,
        window_start=start_s,
        window_end=end_s,
        rule_pack_fingerprint_sha256=fp,
        rule_pack_json=dict(body.rule_pack),
        analytics_table=table,
        rows_processed=0,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    jid = job.id
    background_tasks.add_task(run_backtest_job, jid, engine)

    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "tenant_id": body.tenant_id,
        "window_start": start_s,
        "window_end": end_s,
        "rule_pack_fingerprint_sha256": fp,
        "analytics_table": table,
        "wall_timeout_seconds": settings.backtest_job_timeout_seconds,
        "chunk_size": 10_000,
    }


@router.get("/jobs/{job_id}")
async def get_backtest_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    job = await session.get(BacktestRun, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": str(job.id),
        "tenant_id": job.tenant_id,
        "status": job.status.value,
        "window_start": job.window_start,
        "window_end": job.window_end,
        "analytics_table": job.analytics_table,
        "rows_processed": job.rows_processed,
        "rule_pack_fingerprint_sha256": job.rule_pack_fingerprint_sha256,
        "metrics": job.metrics_json,
        "error_detail": job.error_detail,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
