#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

"""
Export decision_audit rows to JSONL for offline counter replay (Epic C).

Uses synchronous SQLAlchemy against DATABASE_URL (sync URL). Supports SQLite
and PostgreSQL when dependencies are installed.

Usage:
  export DATABASE_URL=postgresql+psycopg://...
  python scripts/replay/export_audit_to_jsonl.py \\
    --tenant-id acme --entity-id user-42 --out /tmp/audit.jsonl --limit 1000

Each line matches the shape expected by replay_aggregates.py:
  tenant_id, entity_id, event_id (trace_id), fields (from payload_snapshot),
  optional metadata echo, ts (prefer logical event_time from snapshot, else created_at).
"""
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED = _REPO_ROOT / "services" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from event_time import event_time_unix_from_payload_snapshot  # noqa: E402


def _sync_database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        print("Set DATABASE_URL", file=sys.stderr)
        raise SystemExit(2)
    if raw.startswith("sqlite+aiosqlite"):
        return raw.replace("sqlite+aiosqlite://", "sqlite://")
    if "+asyncpg" in raw:
        return raw.replace("postgresql+asyncpg", "postgresql+psycopg")
    return raw


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export decision_audit rows to JSONL for replay_aggregates.py")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--entity-id", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, default=5000)
    args = p.parse_args(argv)

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("Install sqlalchemy: pip install sqlalchemy", file=sys.stderr)
        return 2

    url = _sync_database_url()
    engine = create_engine(url)
    lim = max(1, min(args.limit, 50_000))

    q = text(
        """
        SELECT trace_id, tenant_id, entity_id, payload_snapshot, created_at
        FROM decision_audit
        WHERE tenant_id = :tid AND entity_id = :eid
        ORDER BY created_at ASC
        LIMIT :lim
        """
    )

    n = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn, args.out.open("w", encoding="utf-8") as f:
        for row in conn.execute(q, {"tid": args.tenant_id, "eid": args.entity_id, "lim": lim}):
            trace_id, tenant_id, entity_id, payload_snapshot, created_at = row
            trace_id = str(trace_id) if trace_id is not None else ""
            fields: dict[str, Any] = {}
            meta_out: dict[str, Any] = {}
            if isinstance(payload_snapshot, dict):
                inner = payload_snapshot.get("payload")
                fields = dict(inner) if isinstance(inner, dict) else {}
                im = payload_snapshot.get("metadata")
                if isinstance(im, dict):
                    meta_out = dict(im)
            logical_ts: float | None = event_time_unix_from_payload_snapshot(payload_snapshot) if isinstance(payload_snapshot, dict) else None
            ts: float | None = logical_ts
            if ts is None and created_at is not None:
                ts = created_at.timestamp()
            rec = {
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_id": trace_id,
                "fields": fields,
            }
            if meta_out:
                rec["metadata"] = meta_out
            if ts is not None:
                rec["ts"] = ts
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1

    print(f"Wrote {n} row(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
