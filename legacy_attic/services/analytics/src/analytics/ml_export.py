"""Point-in-time (PIT) ML training export: OLAP decision rows + case labels → streamed Parquet.

**Leakage guardrails**

- Feature columns come **only** from the analytics warehouse ``payload_json`` (and identifiers)
  captured at ingest time for that evaluation row. We never read a live feature store or
  recomputed feature vectors for this export.
- ``evaluation_time`` is the warehouse ``created_at`` for the decision row (the inference
  event), not label resolution time.
- Case-management labels are joined **by ``trace_id``** for supervision; they are stored in
  separate columns so trainers can apply horizon / censoring policies explicitly.

Rows are written with ``pyarrow.parquet.ParquetWriter`` in bounded batches (one OLAP page at
a time) — no whole-export ``pandas`` materialisation.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analytics import queries
from analytics.engine import BaseAnalyticsEngine
from analytics.historical_stream import iter_backtest_row_chunks


def _utc_evaluation_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    # DuckDB / drivers may return strings for TIMESTAMP
    s = str(value or "").strip()
    if not s:
        return datetime(1970, 1, 1, tzinfo=UTC)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _pit_schema():
    try:
        import pyarrow as pa
    except ImportError as e:  # pragma: no cover — exercised when optional dep missing
        raise RuntimeError(
            "ml export requires pyarrow; install tarka-analytics[ml_export] or pyarrow"
        ) from e

    return pa.schema(
        [
            ("tenant_id", pa.string()),
            ("trace_id", pa.string()),
            ("entity_id", pa.string()),
            ("evaluation_time", pa.timestamp("us", tz="UTC")),
            ("decision_engine", pa.string()),
            ("risk_score", pa.float64()),
            ("case_management_label", pa.string()),
            ("case_label_source", pa.string()),
            ("dispute_outcome", pa.string()),
            ("feature_payload_json", pa.string()),
        ]
    )


def _empty_label_payload() -> dict[str, Any]:
    return {
        "case_management_label": "unknown",
        "case_label_source": "none",
        "dispute_outcome": "",
    }


def _coerce_label_row(raw: dict[str, Any] | str | None) -> dict[str, str]:
    if raw is None:
        return {k: str(v) for k, v in _empty_label_payload().items()}
    if isinstance(raw, str):
        return {
            "case_management_label": raw,
            "case_label_source": "api_string",
            "dispute_outcome": "",
        }
    if isinstance(raw, dict):
        return {
            "case_management_label": str(raw.get("case_management_label") or "unknown"),
            "case_label_source": str(raw.get("case_label_source") or "none"),
            "dispute_outcome": str(raw.get("dispute_outcome") or ""),
        }
    return {k: str(v) for k, v in _empty_label_payload().items()}


def _payload_as_dict(pj: Any) -> dict[str, Any] | None:
    if isinstance(pj, dict):
        return pj
    if isinstance(pj, str) and pj.strip():
        try:
            parsed = json.loads(pj)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _serialize_feature_payload(
    pj: Any,
    *,
    payload_json_keys: list[str] | None,
) -> str:
    """Serialize OLAP ``payload_json`` for Parquet; optional key subset for ML feature columns."""
    if pj is None:
        return ""
    d = _payload_as_dict(pj)
    if d is not None:
        if payload_json_keys:
            keys = [k.strip() for k in payload_json_keys if k and str(k).strip()]
            sub = {k: d[k] for k in keys if k in d}
            return json.dumps(sub, separators=(",", ":"), default=str)
        return json.dumps(d, separators=(",", ":"), default=str)
    if isinstance(pj, (dict, list)):
        return json.dumps(pj, separators=(",", ":"), default=str)
    return str(pj)


def _build_batch_table(
    *,
    olap_page: list[dict[str, Any]],
    labels_by_trace: dict[str, Any],
    payload_json_keys: list[str] | None = None,
    dispute_outcome_allowlist: frozenset[str] | None = None,
) -> Any:
    import pyarrow as pa

    len(olap_page)
    tenant_ids: list[str | None] = []
    trace_ids: list[str | None] = []
    entity_ids: list[str | None] = []
    eval_ts: list[datetime] = []
    decisions: list[str | None] = []
    scores: list[float] = []
    cm_labels: list[str] = []
    sources: list[str] = []
    outcomes: list[str] = []
    payloads: list[str] = []

    for row in olap_page:
        tid = str(row.get("tenant_id") or "")
        tr = str(row.get("trace_id") or "")
        eid = str(row.get("entity_id") or "")
        raw_l = labels_by_trace.get(tr)
        coerced = _coerce_label_row(raw_l if isinstance(raw_l, (dict, str)) else None)
        outcome = coerced["dispute_outcome"]
        if dispute_outcome_allowlist is not None and len(dispute_outcome_allowlist) > 0:
            if outcome not in dispute_outcome_allowlist:
                continue
        tenant_ids.append(tid)
        trace_ids.append(tr)
        entity_ids.append(eid)
        eval_ts.append(_utc_evaluation_ts(row.get("created_at")))
        decisions.append(str(row.get("decision") or ""))
        try:
            scores.append(float(row.get("score") or 0.0))
        except (TypeError, ValueError):
            scores.append(0.0)
        cm_labels.append(coerced["case_management_label"])
        sources.append(coerced["case_label_source"])
        outcomes.append(outcome)
        pj = row.get("payload_json")
        payloads.append(_serialize_feature_payload(pj, payload_json_keys=payload_json_keys))

    return pa.Table.from_arrays(
        [
            pa.array(tenant_ids, type=pa.string()),
            pa.array(trace_ids, type=pa.string()),
            pa.array(entity_ids, type=pa.string()),
            pa.array(eval_ts, type=pa.timestamp("us", tz="UTC")),
            pa.array(decisions, type=pa.string()),
            pa.array(scores, type=pa.float64()),
            pa.array(cm_labels, type=pa.string()),
            pa.array(sources, type=pa.string()),
            pa.array(outcomes, type=pa.string()),
            pa.array(payloads, type=pa.string()),
        ],
        schema=_pit_schema(),
    )


@dataclass(frozen=True)
class PitMlExportStats:
    """Row counts for observability."""

    rows_written: int
    chunks_processed: int


def run_point_in_time_ml_export(
    engine: BaseAnalyticsEngine,
    *,
    table: str,
    tenant_id: str,
    window_start_s: str,
    window_end_s: str,
    out_path: Path,
    label_fetcher: Callable[[list[str]], dict[str, Any]],
    chunk_size: int = 10_000,
    clickhouse_max_execution_seconds: int = 60,
    max_rows: int = 500_000,
    payload_json_keys: list[str] | None = None,
    dispute_outcome_allowlist: frozenset[str] | None = None,
    on_progress: Callable[[PitMlExportStats], None] | None = None,
) -> PitMlExportStats:
    """Stream OLAP pages, join labels per page, append Parquet batches.

    ``label_fetcher`` receives distinct non-empty trace_ids for the current page and must return
    a mapping ``trace_id ->`` either a normalized label string or a dict with keys
    ``case_management_label``, ``case_label_source``, ``dispute_outcome`` (as returned by
    case-api ``POST /v1/ml/training-labels/by-trace``).
    """
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("ml export requires pyarrow; install pyarrow") from e

    queries.validate_sql_identifier(table)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema = _pit_schema()
    writer: Any | None = None
    rows_written = 0
    chunks = 0
    try:
        for page in iter_backtest_row_chunks(
            engine,
            table,
            tenant_id,
            window_start_s,
            window_end_s,
            chunk_size=chunk_size,
            clickhouse_max_execution_seconds=clickhouse_max_execution_seconds,
        ):
            chunks += 1
            tids = sorted(
                {str(r.get("trace_id") or "") for r in page if str(r.get("trace_id") or "").strip()}
            )
            labels: dict[str, Any] = {}
            if tids:
                labels = dict(label_fetcher(tids))
            batch = _build_batch_table(
                olap_page=page,
                labels_by_trace=labels,
                payload_json_keys=payload_json_keys,
                dispute_outcome_allowlist=dispute_outcome_allowlist,
            )
            if batch.num_rows == 0:
                if on_progress is not None:
                    on_progress(
                        PitMlExportStats(rows_written=rows_written, chunks_processed=chunks)
                    )
                if rows_written >= max_rows:
                    break
                continue
            if writer is None:
                writer = pq.ParquetWriter(str(out_path), schema, compression="zstd")
            writer.write_table(batch)
            n = batch.num_rows
            rows_written += n
            if on_progress is not None:
                on_progress(PitMlExportStats(rows_written=rows_written, chunks_processed=chunks))
            if rows_written >= max_rows:
                break
    finally:
        if writer is not None:
            writer.close()
    return PitMlExportStats(rows_written=rows_written, chunks_processed=chunks)


def default_local_export_path(*, tenant_id: str, base_dir: Path) -> Path:
    safe_tenant = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-"))[:120] or "tenant"
    uid = uuid.uuid4().hex[:12]
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"pit_ml_{safe_tenant}_{uid}.parquet"


def upload_parquet_presigned_s3(
    *,
    local_path: Path,
    bucket: str,
    object_key: str,
    presign_ttl_seconds: int,
) -> str:
    """Upload a finished Parquet file to S3 and return a presigned HTTPS GET URL."""
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("S3 upload requires boto3") from e

    client = boto3.client("s3")
    client.upload_file(str(local_path), bucket, object_key)
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=int(presign_ttl_seconds),
        )
    )


def pit_export_uri_for_sink(
    *,
    local_path: Path,
    s3_bucket: str,
    s3_object_key: str,
    presign_ttl_seconds: int,
) -> tuple[str, str | None]:
    """Return ``(uri_for_clients, presigned_url_or_none)``.

    Micro / local: ``uri_for_clients`` is a ``file://`` URI; ``presigned_url`` is None.
    Production: ``uri_for_clients`` is the presigned URL (same as second tuple element).
    """
    bucket = (s3_bucket or "").strip()
    if bucket:
        url = upload_parquet_presigned_s3(
            local_path=local_path,
            bucket=bucket,
            object_key=s3_object_key,
            presign_ttl_seconds=presign_ttl_seconds,
        )
        return url, url
    abs_path = local_path.resolve()
    return abs_path.as_uri(), None
