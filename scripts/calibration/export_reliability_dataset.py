#!/usr/bin/env python3
from __future__ import annotations

"""Export decision_audit rows for offline reliability / calibration analysis (CSV).

Reads the **Decision API** database via DATABASE_URL (same DB as `decision_audit`).
For analyst labels, join the exported CSV with case-api exports or your warehouse.

Usage::

    export DATABASE_URL=postgresql+asyncpg://...
    python scripts/calibration/export_reliability_dataset.py --out /tmp/reliability.csv --tenant-id acme --limit 5000
"""


import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_dec_src = _REPO / "services" / "decision-api" / "src"
if str(_dec_src) not in sys.path:
    sys.path.insert(0, str(_dec_src))


async def _run(args: argparse.Namespace) -> int:
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 1
    engine = create_async_engine(url)

    tenant_filter = "AND a.tenant_id = :tid" if args.tenant_id else ""
    params: dict[str, Any] = {"lim": args.limit}
    if args.tenant_id:
        params["tid"] = args.tenant_id.strip()

    is_sqlite = "sqlite" in url.lower()
    if is_sqlite:
        inf_expr = "json_extract(a.payload_snapshot, '$.inference_context')"
    else:
        inf_expr = "a.payload_snapshot->'inference_context'"

    sql = text(
        f"""
        SELECT
          CAST(a.trace_id AS TEXT) AS trace_id,
          a.tenant_id,
          a.entity_id,
          a.event_type,
          a.decision,
          a.score,
          {inf_expr} AS inference_json,
          a.created_at
        FROM decision_audit a
        WHERE 1=1 {tenant_filter}
        ORDER BY a.created_at DESC
        LIMIT :lim
        """
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with engine.connect() as conn:
        result = await conn.execute(sql, params)
        rows = result.mappings().all()

    fieldnames = [
        "trace_id",
        "tenant_id",
        "entity_id",
        "event_type",
        "decision",
        "score",
        "integrity_confidence",
        "confidence_tier",
        "calibration_profile",
        "expected_calibration_version",
        "y_label",
        "created_at",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            inf_raw = r.get("inference_json")
            if isinstance(inf_raw, str):
                try:
                    inf = json.loads(inf_raw)
                except json.JSONDecodeError:
                    inf = {}
            elif isinstance(inf_raw, dict):
                inf = inf_raw
            else:
                inf = {}
            w.writerow(
                {
                    "trace_id": r["trace_id"],
                    "tenant_id": r["tenant_id"],
                    "entity_id": r["entity_id"],
                    "event_type": r["event_type"],
                    "decision": r["decision"],
                    "score": r["score"],
                    "integrity_confidence": inf.get("integrity_confidence", ""),
                    "confidence_tier": inf.get("confidence_tier", ""),
                    "calibration_profile": inf.get("calibration_profile", ""),
                    "expected_calibration_version": inf.get("expected_calibration_version", ""),
                    "y_label": "",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else "",
                }
            )

    await engine.dispose()
    print(f"wrote {len(rows)} rows to {out_path}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Output CSV path")
    p.add_argument("--tenant-id", default="", help="Filter tenant_id")
    p.add_argument("--limit", type=int, default=10_000, help="Max rows")
    p.add_argument("--database-url", default="", help="Override DATABASE_URL")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
