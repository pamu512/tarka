"""ClickHouse helpers for loading the latest ``EvidenceManifest`` row by ``entity_id``."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE = "tarka_audit"
_DEFAULT_TABLE = "evidence_manifests"


def _qualified_manifest_table() -> str:
    database = (os.environ.get("CLICKHOUSE_DATABASE") or _DEFAULT_DATABASE).strip() or _DEFAULT_DATABASE
    table = (os.environ.get("CLICKHOUSE_EVIDENCE_MANIFESTS_TABLE") or _DEFAULT_TABLE).strip() or _DEFAULT_TABLE
    return f"`{database}`.`{table}`"


def _row_to_manifest_projection(row: dict[str, Any]) -> dict[str, Any]:
    trace_raw = row.get("trace_json")
    trace_steps: list[dict[str, Any]] = []
    if isinstance(trace_raw, list):
        for step in trace_raw:
            if isinstance(step, dict):
                trace_steps.append(dict(step))
    elif isinstance(trace_raw, str) and trace_raw.strip():
        try:
            parsed = json.loads(trace_raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            for step in parsed:
                if isinstance(step, dict):
                    trace_steps.append(dict(step))

    signals_raw = row.get("signals")
    signals: dict[str, Any] = dict(signals_raw) if isinstance(signals_raw, dict) else {}

    manifest_id = row.get("manifest_id")
    return {
        "manifest_id": str(manifest_id).strip() if manifest_id is not None else None,
        "trace_steps": trace_steps,
        "signals": signals,
        "engine_version": str(row.get("engine_version") or "").strip() or None,
        "timestamp_ns": row.get("timestamp_ns"),
        "final_decision": row.get("final_decision"),
        "total_execution_time_us": row.get("total_execution_time_us"),
    }


def _fetch_most_recent_manifest_sync(client: Any, *, entity_id: str) -> dict[str, Any] | None:
    token = (entity_id or "").strip()
    if not token:
        return None

    table_ref = _qualified_manifest_table()
    sql = f"""
        SELECT
            manifest_id,
            trace_json,
            signals,
            engine_version,
            timestamp_ns,
            final_decision,
            total_execution_time_us
        FROM {table_ref}
        WHERE (
            mapContains(signals, 'entity_id') AND signals['entity_id'] = %(entity_id)s
        ) OR (
            mapContains(signals, 'transaction_id') AND signals['transaction_id'] = %(entity_id)s
        )
        ORDER BY timestamp_ns DESC
        LIMIT 1
    """
    result = client.query(sql, parameters={"entity_id": token})
    rows = getattr(result, "result_rows", None) or []
    if not rows:
        return None

    columns = getattr(result, "column_names", None) or [
        "manifest_id",
        "trace_json",
        "signals",
        "engine_version",
        "timestamp_ns",
        "final_decision",
        "total_execution_time_us",
    ]
    row_dict = dict(zip(columns, rows[0], strict=False))
    projection = _row_to_manifest_projection(row_dict)
    if not projection.get("manifest_id") and not projection.get("trace_steps"):
        return None
    return projection


async def fetch_most_recent_evidence_manifest(
    clickhouse_client: Any | None,
    *,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return the newest ClickHouse ``EvidenceManifest`` projection for ``entity_id``, or ``None``."""
    if clickhouse_client is None:
        return None
    token = (entity_id or "").strip()
    if not token:
        return None
    try:
        return await asyncio.to_thread(
            _fetch_most_recent_manifest_sync,
            clickhouse_client,
            entity_id=token,
        )
    except Exception:
        logger.exception(
            "evidence_manifest_fetch_clickhouse_failed entity_id=%s",
            token,
        )
        return None
