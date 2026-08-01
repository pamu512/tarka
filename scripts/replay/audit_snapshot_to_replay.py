#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

"""Convert decision_audit-shaped rows (payload_snapshot) → replay_aggregates JSONL.

CI uses fixtures/audit_payload_snapshot.jsonl (no Postgres). Live export uses
export_audit_to_jsonl.py which shares audit_row_to_replay_record().
"""

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED = _REPO_ROOT / "services" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from event_time import event_time_unix_from_payload_snapshot  # noqa: E402


def _created_at_unix(created_at: Any) -> float | None:
    if created_at is None:
        return None
    if hasattr(created_at, "timestamp"):
        try:
            return float(created_at.timestamp())
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
        f = float(created_at)
        if f > 1e12:
            f = f / 1000.0
        return f if f > 0 else None
    if isinstance(created_at, str):
        s = created_at.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            return None
    return None


def audit_row_to_replay_record(
    *,
    trace_id: Any,
    tenant_id: Any,
    entity_id: Any,
    payload_snapshot: Any,
    created_at: Any = None,
) -> dict[str, Any]:
    """Map one decision_audit row to a replay_aggregates.py record."""
    fields: dict[str, Any] = {}
    meta_out: dict[str, Any] = {}
    if isinstance(payload_snapshot, dict):
        inner = payload_snapshot.get("payload")
        fields = dict(inner) if isinstance(inner, dict) else {}
        im = payload_snapshot.get("metadata")
        if isinstance(im, dict):
            meta_out = dict(im)
    logical_ts: float | None = (
        event_time_unix_from_payload_snapshot(payload_snapshot)
        if isinstance(payload_snapshot, dict)
        else None
    )
    ts = logical_ts if logical_ts is not None else _created_at_unix(created_at)
    rec: dict[str, Any] = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "event_id": str(trace_id) if trace_id is not None else "",
        "fields": fields,
    }
    if meta_out:
        rec["metadata"] = meta_out
    if ts is not None:
        rec["ts"] = ts
    return rec


def convert_audit_jsonl(src: Path, dst: Path) -> int:
    """Read audit-shaped JSONL; write replay JSONL. Returns row count."""
    n = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"audit row must be object, got {type(row).__name__}")
            rec = audit_row_to_replay_record(
                trace_id=row.get("trace_id") or row.get("event_id"),
                tenant_id=row.get("tenant_id"),
                entity_id=row.get("entity_id"),
                payload_snapshot=row.get("payload_snapshot"),
                created_at=row.get("created_at"),
            )
            if rec.get("tenant_id") is None or rec.get("entity_id") is None:
                raise ValueError("audit row missing tenant_id or entity_id")
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert decision_audit-shaped JSONL to replay_aggregates JSONL"
    )
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    n = convert_audit_jsonl(args.input, args.out)
    print(f"Wrote {n} row(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
