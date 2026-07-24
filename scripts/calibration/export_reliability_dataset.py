#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any

"""Export decision_audit rows for offline reliability / calibration analysis (CSV).

Prefer the Decision API when running:

    GET /v1/calibration/reliability-export.csv?tenant_id=acme&limit=5000

This CLI reads the same DB via DATABASE_URL for air-gapped / batch jobs.

Usage::

    export DATABASE_URL=postgresql+asyncpg://...
    python scripts/calibration/export_reliability_dataset.py --out /tmp/reliability.csv --tenant-id acme --limit 5000
"""
_REPO = Path(__file__).resolve().parents[2]
_dec_src = _REPO / "services" / "decision-api" / "src"
if str(_dec_src) not in sys.path:
    sys.path.insert(0, str(_dec_src))


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from decision_api.reliability_export import (
        RELIABILITY_CSV_FIELDS,
        audit_row_to_export_dict,
        parse_inference_json_cell,
    )

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
        payload_expr = "a.payload_snapshot"
    else:
        inf_expr = "a.payload_snapshot->'inference_context'"
        payload_expr = "a.payload_snapshot"

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
          {payload_expr} AS payload_snapshot,
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

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(RELIABILITY_CSV_FIELDS))
        w.writeheader()
        for r in rows:
            payload = r.get("payload_snapshot")
            if not isinstance(payload, dict):
                inf = parse_inference_json_cell(r.get("inference_json"))
                payload = {"inference_context": inf}
            w.writerow(
                audit_row_to_export_dict(
                    {
                        "trace_id": r["trace_id"],
                        "tenant_id": r["tenant_id"],
                        "entity_id": r["entity_id"],
                        "event_type": r["event_type"],
                        "decision": r["decision"],
                        "score": r["score"],
                        "payload_snapshot": payload,
                        "created_at": r["created_at"],
                    }
                )
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
