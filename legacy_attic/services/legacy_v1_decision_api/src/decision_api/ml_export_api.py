"""Point-in-time ML training export (OLAP + case labels → Parquet, local or S3)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from collections.abc import Callable
from typing import Any, Literal

import anyio
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from analytics.engine import BaseAnalyticsEngine
from analytics.ml_export import (
    PitMlExportStats,
    default_local_export_path,
    pit_export_uri_for_sink,
    run_point_in_time_ml_export,
)

from decision_api.config import settings
from decision_api.deps import require_analytics_engine
from tarka_core.internal_monitor import InternalMonitor

import sys

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

log = logging.getLogger("decision-api.ml_export")

router = APIRouter(prefix="/v1/ml/export", tags=["ml-export"])

_jobs_lock = Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _normalize_dispute_allowlist(raw: list[str] | None) -> frozenset[str] | None:
    if not raw:
        return None
    out: set[str] = set()
    for x in raw:
        s = str(x).strip()
        if s == "__unlabeled__":
            out.add("")
        else:
            out.add(s)
    return frozenset(out) if out else None


def _job_update(job_id: str, **patch: Any) -> None:
    with _jobs_lock:
        row = _jobs.get(job_id)
        if row is None:
            return
        row.update(patch)


def _job_get(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        r = _jobs.get(job_id)
        return dict(r) if r else None


def _upstream_headers() -> dict[str, str]:
    key = settings.upstream_api_key.strip() if settings.upstream_api_key.strip() else ""
    if not key:
        key = (
            settings.api_keys.split(",")[0].strip() if settings.api_keys.strip() else ""
        )
    return {"x-api-key": key} if key else {}


class PitParquetExportRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    window_start: str = Field(
        ..., description="ISO-8601 UTC inclusive lower bound for evaluation_time"
    )
    window_end: str = Field(
        ..., description="ISO-8601 UTC exclusive upper bound for evaluation_time"
    )
    analytics_table: str | None = Field(
        default=None,
        max_length=128,
        description="Validated OLAP table (default: settings.clickhouse_analytics_events_table)",
    )
    chunk_size: int = Field(default=10_000, ge=100, le=50_000)
    payload_json_keys: list[str] | None = Field(
        default=None,
        max_length=64,
        description="Subset of keys from warehouse payload_json objects to embed in feature_payload_json (max 64).",
    )
    dispute_outcome_allowlist: list[str] | None = Field(
        default=None,
        max_length=32,
        description="If non-empty, only rows whose Case API dispute_outcome is in this set. "
        "Use __unlabeled__ for traces with no dispute outcome string.",
    )

    @field_validator("payload_json_keys")
    @classmethod
    def _cap_payload_keys(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [str(x).strip() for x in v if str(x).strip()]
        if len(cleaned) > 64:
            raise ValueError("payload_json_keys must contain at most 64 entries")
        return cleaned

    @field_validator("dispute_outcome_allowlist")
    @classmethod
    def _cap_dispute_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if len(v) > 32:
            raise ValueError(
                "dispute_outcome_allowlist must contain at most 32 entries"
            )
        return v


class PitParquetExportResponse(BaseModel):
    rows_written: int
    chunks_processed: int
    local_path: str
    artifact_uri: str
    presigned_get_url: str | None = None
    pit_note: str = (
        "Features are taken only from warehouse payload_json at ingest (evaluation_time = created_at). "
        "Labels come from case-api disputes / case labels by trace_id."
    )


class PitParquetJobStartResponse(BaseModel):
    job_id: str
    status: Literal["PENDING"] = "PENDING"


PitExportJobStatusLiteral = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]


class PitParquetJobStatusResponse(BaseModel):
    job_id: str
    status: PitExportJobStatusLiteral
    progress_pct: int = Field(ge=0, le=100)
    rows_written: int
    chunks_processed: int
    max_rows: int
    error: str | None = None
    result: PitParquetExportResponse | None = None


def _sync_run_export(
    req: PitParquetExportRequest,
    engine: BaseAnalyticsEngine,
    *,
    on_progress: Callable[[PitMlExportStats], None] | None = None,
) -> dict[str, Any]:
    tbl = (
        req.analytics_table or settings.clickhouse_analytics_events_table or ""
    ).strip()
    if not tbl:
        raise RuntimeError("analytics_table is empty")
    base = Path(settings.ml_export_local_dir).expanduser()
    out_path = default_local_export_path(tenant_id=req.tenant_id, base_dir=base)
    case_url = (settings.case_api_url or "").strip().rstrip("/")
    if not case_url:
        raise RuntimeError("CASE_API_URL is not configured")

    def label_fetch(trace_ids: list[str]) -> dict[str, Any]:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{case_url}/v1/ml/training-labels/by-trace",
                json={"tenant_id": req.tenant_id, "trace_ids": trace_ids},
                headers=_upstream_headers(),
            )
            r.raise_for_status()
            body = r.json()
            return dict(body.get("labels") or {})

    allow = _normalize_dispute_allowlist(req.dispute_outcome_allowlist)

    stats = run_point_in_time_ml_export(
        engine,
        table=tbl,
        tenant_id=req.tenant_id.strip(),
        window_start_s=req.window_start.strip(),
        window_end_s=req.window_end.strip(),
        out_path=out_path,
        label_fetcher=label_fetch,
        chunk_size=int(req.chunk_size),
        clickhouse_max_execution_seconds=max(
            30, settings.clickhouse_statement_timeout_ms // 1000
        ),
        max_rows=int(settings.ml_export_max_rows),
        payload_json_keys=req.payload_json_keys,
        dispute_outcome_allowlist=allow,
        on_progress=on_progress,
    )
    if stats.rows_written == 0:
        try:
            out_path.unlink(missing_ok=True)
        except OSError as exc:
            InternalMonitor.log_suppressed_error(
                exc, context="ml_export_cleanup_empty_parquet", domain="ml_export"
            )
        raise RuntimeError("no evaluation rows in window for export")

    prefix = (settings.ml_export_s3_prefix or "pit-exports").strip().strip("/")
    safe_tenant = (
        "".join(c for c in req.tenant_id if c.isalnum() or c in ("_", "-"))[:80]
        or "tenant"
    )
    object_key = f"{prefix}/{safe_tenant}/pit_ml_{uuid.uuid4().hex[:16]}.parquet"
    uri, presigned = pit_export_uri_for_sink(
        local_path=out_path,
        s3_bucket=(settings.ml_export_s3_bucket or "").strip(),
        s3_object_key=object_key,
        presign_ttl_seconds=int(settings.ml_export_presign_ttl_seconds),
    )
    return {
        "rows_written": stats.rows_written,
        "chunks_processed": stats.chunks_processed,
        "local_path": str(out_path.resolve()),
        "artifact_uri": uri,
        "presigned_get_url": presigned,
    }


def _progress_pct_for_rows(rows_written: int) -> int:
    cap = max(1, int(settings.ml_export_max_rows))
    return min(99, int(rows_written * 100 / cap))


async def _run_pit_export_job(
    job_id: str, body: PitParquetExportRequest, engine: BaseAnalyticsEngine
) -> None:
    _job_update(job_id, status="RUNNING", progress_pct=0)

    def on_progress(st: PitMlExportStats) -> None:
        _job_update(
            job_id,
            rows_written=st.rows_written,
            chunks_processed=st.chunks_processed,
            progress_pct=_progress_pct_for_rows(st.rows_written),
            status="RUNNING",
        )

    try:
        payload = await anyio.to_thread.run_sync(
            lambda: _sync_run_export(body, engine, on_progress=on_progress)
        )
    except RuntimeError as e:
        msg = str(e)
        _job_update(job_id, status="FAILED", progress_pct=0, error=msg, result=None)
        return
    except httpx.HTTPStatusError as e:
        log.warning("case-api label fetch failed (job): %s", e)
        _job_update(
            job_id,
            status="FAILED",
            error=f"case-api training-labels error: {e.response.status_code}",
            result=None,
        )
        return
    except httpx.RequestError as e:
        log.warning("case-api unreachable (job): %s", e)
        _job_update(
            job_id, status="FAILED", error=f"case-api unreachable: {e}", result=None
        )
        return
    except Exception as e:  # pragma: no cover — defensive
        log.exception("pit export job failed")
        _job_update(job_id, status="FAILED", error=str(e), result=None)
        return

    result = PitParquetExportResponse(
        rows_written=int(payload["rows_written"]),
        chunks_processed=int(payload["chunks_processed"]),
        local_path=str(payload["local_path"]),
        artifact_uri=str(payload["artifact_uri"]),
        presigned_get_url=payload.get("presigned_get_url"),
    )
    _job_update(
        job_id,
        status="SUCCEEDED",
        progress_pct=100,
        rows_written=result.rows_written,
        chunks_processed=result.chunks_processed,
        error=None,
        result=result.model_dump(),
    )


@router.post("/pit-parquet/jobs", response_model=PitParquetJobStartResponse)
async def enqueue_pit_parquet_job(
    body: PitParquetExportRequest,
    background_tasks: BackgroundTasks,
    _user=Depends(require_role("analyst")),
    engine: BaseAnalyticsEngine = Depends(require_analytics_engine),
) -> PitParquetJobStartResponse:
    """Start a PIT Parquet export in the background; poll ``GET /pit-parquet/jobs/{job_id}`` for progress."""
    case_url = (settings.case_api_url or "").strip().rstrip("/")
    if not case_url:
        raise HTTPException(status_code=503, detail="CASE_API_URL is not configured")

    job_id = uuid.uuid4().hex
    max_rows = int(settings.ml_export_max_rows)
    now = datetime.now(timezone.utc).isoformat()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "PENDING",
            "progress_pct": 0,
            "rows_written": 0,
            "chunks_processed": 0,
            "max_rows": max_rows,
            "error": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
        }

    background_tasks.add_task(_run_pit_export_job, job_id, body, engine)
    return PitParquetJobStartResponse(job_id=job_id, status="PENDING")


@router.get("/pit-parquet/jobs/{job_id}", response_model=PitParquetJobStatusResponse)
async def get_pit_parquet_job(
    job_id: str,
    _user=Depends(require_role("analyst")),
) -> PitParquetJobStatusResponse:
    row = _job_get(job_id.strip())
    if row is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    res_raw = row.get("result")
    result = (
        PitParquetExportResponse.model_validate(res_raw)
        if isinstance(res_raw, dict)
        else None
    )
    return PitParquetJobStatusResponse(
        job_id=job_id.strip(),
        status=row["status"],
        progress_pct=int(row.get("progress_pct") or 0),
        rows_written=int(row.get("rows_written") or 0),
        chunks_processed=int(row.get("chunks_processed") or 0),
        max_rows=int(row.get("max_rows") or int(settings.ml_export_max_rows)),
        error=row.get("error"),
        result=result,
    )


@router.post("/pit-parquet", response_model=PitParquetExportResponse)
async def export_pit_parquet_training_set(
    body: PitParquetExportRequest,
    _user=Depends(require_role("analyst")),
    engine: BaseAnalyticsEngine = Depends(require_analytics_engine),
) -> PitParquetExportResponse:
    """Export PIT-correct rows for ML training (streamed Parquet; local path or S3 presigned URL)."""
    try:
        payload = await anyio.to_thread.run_sync(lambda: _sync_run_export(body, engine))
    except RuntimeError as e:
        msg = str(e)
        if "CASE_API_URL" in msg:
            raise HTTPException(status_code=503, detail=msg) from e
        if "no evaluation rows" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=500, detail=msg) from e
    except httpx.HTTPStatusError as e:
        log.warning("case-api label fetch failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"case-api training-labels error: {e.response.status_code}",
        ) from e
    except httpx.RequestError as e:
        log.warning("case-api unreachable: %s", e)
        raise HTTPException(status_code=502, detail=f"case-api unreachable: {e}") from e

    return PitParquetExportResponse(
        rows_written=int(payload["rows_written"]),
        chunks_processed=int(payload["chunks_processed"]),
        local_path=str(payload["local_path"]),
        artifact_uri=str(payload["artifact_uri"]),
        presigned_get_url=payload.get("presigned_get_url"),
    )
