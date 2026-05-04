"""Point-in-time ML training export (OLAP + case labels → Parquet, local or S3)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from analytics.engine import BaseAnalyticsEngine
from analytics.ml_export import (
    default_local_export_path,
    pit_export_uri_for_sink,
    run_point_in_time_ml_export,
)

from decision_api.config import settings
from decision_api.deps import require_analytics_engine

import sys

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

log = logging.getLogger("decision-api.ml_export")

router = APIRouter(prefix="/v1/ml/export", tags=["ml-export"])


def _upstream_headers() -> dict[str, str]:
    key = settings.upstream_api_key.strip() if settings.upstream_api_key.strip() else ""
    if not key:
        key = settings.api_keys.split(",")[0].strip() if settings.api_keys.strip() else ""
    return {"x-api-key": key} if key else {}


class PitParquetExportRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    window_start: str = Field(..., description="ISO-8601 UTC inclusive lower bound for evaluation_time")
    window_end: str = Field(..., description="ISO-8601 UTC exclusive upper bound for evaluation_time")
    analytics_table: str | None = Field(
        default=None,
        max_length=128,
        description="Validated OLAP table (default: settings.clickhouse_analytics_events_table)",
    )
    chunk_size: int = Field(default=10_000, ge=100, le=50_000)


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


def _sync_run_export(req: PitParquetExportRequest, engine: BaseAnalyticsEngine) -> dict[str, Any]:
    tbl = (req.analytics_table or settings.clickhouse_analytics_events_table or "").strip()
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

    stats = run_point_in_time_ml_export(
        engine,
        table=tbl,
        tenant_id=req.tenant_id.strip(),
        window_start_s=req.window_start.strip(),
        window_end_s=req.window_end.strip(),
        out_path=out_path,
        label_fetcher=label_fetch,
        chunk_size=int(req.chunk_size),
        clickhouse_max_execution_seconds=max(30, settings.clickhouse_statement_timeout_ms // 1000),
        max_rows=int(settings.ml_export_max_rows),
    )
    if stats.rows_written == 0:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("no evaluation rows in window for export")

    prefix = (settings.ml_export_s3_prefix or "pit-exports").strip().strip("/")
    safe_tenant = "".join(c for c in req.tenant_id if c.isalnum() or c in ("_", "-"))[:80] or "tenant"
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
