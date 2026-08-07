"""Append-only host action sink for L3 ops (internal JSONL)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]


def sink_path() -> Path:
    override = os.environ.get("TARKA_HOST_ACTION_LOG_PATH", "").strip()
    if override:
        return Path(override)
    return _REPO_ROOT / "docs" / "compliance" / "host_action_log.jsonl"


def sink_uri() -> str:
    return f"internal:jsonl:{sink_path()}"


def append_host_action(
    *,
    tenant_id: str,
    action: str,
    entity_id: str | None = None,
    trace_id: str | None = None,
    actor: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    act = (action or "").strip()
    if not tid or not act:
        raise ValueError("tenant_id and action required")
    rec = {
        "schema_id": "tarka.host_action/v1",
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tenant_id": tid,
        "action": act[:128],
        "entity_id": (entity_id or "").strip()[:256] or None,
        "trace_id": (trace_id or "").strip()[:128] or None,
        "actor": (actor or "operator").strip()[:128],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }
    path = sink_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def count_actions(tenant_id: str | None = None) -> int:
    path = sink_path()
    if not path.is_file():
        return 0
    tid = (tenant_id or "").strip()
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if not tid:
                n += 1
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("tenant_id") == tid:
                n += 1
    return n
