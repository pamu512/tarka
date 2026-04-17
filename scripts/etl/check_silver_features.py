#!/usr/bin/env python3
"""
Silver-layer quality gate for exported feature / audit JSONL (v1.2.5 E2).

Checks each line for tenant_id, entity_id, event_type (enum), numeric amount when present.
Exits non-zero if violation rate exceeds --max-violation-rate.

Example:
  python scripts/etl/check_silver_features.py --input export.jsonl --max-violation-rate 0.01
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VALID_EVENT_TYPES = frozenset({"login", "payment", "signup", "device", "session", "custom"})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check JSONL silver feature rows.")
    p.add_argument("--input", type=Path, required=True, help="JSONL file (one JSON object per line)")
    p.add_argument(
        "--max-violation-rate",
        type=float,
        default=0.0,
        help="Fail if violations / rows > this (0 = any violation fails)",
    )
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    total = 0
    violations = 0
    reasons: list[str] = []

    with args.input.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                violations += 1
                reasons.append(f"line {total}: invalid JSON ({e})")
                continue
            if not isinstance(row, dict):
                violations += 1
                reasons.append(f"line {total}: not an object")
                continue

            tid = row.get("tenant_id")
            eid = row.get("entity_id")
            et = row.get("event_type")

            if tid is None or (isinstance(tid, str) and not tid.strip()):
                violations += 1
                reasons.append(f"line {total}: missing tenant_id")
            if eid is None or (isinstance(eid, str) and not eid.strip()):
                violations += 1
                reasons.append(f"line {total}: missing entity_id")
            if et is not None and str(et).strip() and str(et).strip() not in VALID_EVENT_TYPES:
                violations += 1
                reasons.append(f"line {total}: invalid event_type {et!r}")

            payload = row.get("payload")
            if isinstance(payload, dict) and "amount" in payload:
                try:
                    float(payload["amount"])
                except (TypeError, ValueError):
                    violations += 1
                    reasons.append(f"line {total}: amount not numeric")

    rate = (violations / total) if total else 0.0
    print(f"rows={total} violations={violations} rate={rate:.6f}")
    if reasons[:10]:
        for r in reasons[:10]:
            print(r, file=sys.stderr)
        if len(reasons) > 10:
            print(f"... and {len(reasons) - 10} more", file=sys.stderr)

    if total == 0:
        print("No rows to check.", file=sys.stderr)
        return 1

    if rate > args.max_violation_rate:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
