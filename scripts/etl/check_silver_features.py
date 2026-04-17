#!/usr/bin/env python3
"""Lightweight Silver-layer checks on JSONL feature rows (stdin or file).

Each line: JSON object with at least tenant_id, entity_id, event_type.
Optional: amount (number), currency (string).

Exit 0 if checks pass; exit 1 with stderr summary if violations exceed --max-violation-rate.

Usage:
  python scripts/etl/check_silver_features.py < export.jsonl
  python scripts/etl/check_silver_features.py --file export.jsonl --max-violation-rate 0.01
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

ALLOWED_EVENT_TYPES = frozenset({"login", "payment", "signup", "device", "session", "custom"})


def _check_row(obj: dict[str, Any], line_no: int) -> list[str]:
    errs: list[str] = []
    for k in ("tenant_id", "entity_id", "event_type"):
        v = obj.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            errs.append(f"line {line_no}: missing or empty {k}")
    et = str(obj.get("event_type", "")).strip().lower()
    if et and et not in ALLOWED_EVENT_TYPES:
        errs.append(f"line {line_no}: invalid event_type {et!r}")
    if "amount" in obj and obj["amount"] is not None:
        try:
            float(obj["amount"])
        except (TypeError, ValueError):
            errs.append(f"line {line_no}: amount not numeric")
    return errs


def run(fp: TextIO, max_violation_rate: float) -> int:
    total = 0
    violations = 0
    all_errs: list[str] = []
    for i, line in enumerate(fp, 1):
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            violations += 1
            all_errs.append(f"line {i}: invalid JSON")
            continue
        if not isinstance(obj, dict):
            violations += 1
            all_errs.append(f"line {i}: not a JSON object")
            continue
        errs = _check_row(obj, i)
        if errs:
            violations += len(errs)
            all_errs.extend(errs)
    if total == 0:
        print("no rows", file=sys.stderr)
        return 1
    rate = violations / max(total, 1)
    print(f"rows={total} violation_events={violations} rate={rate:.4f}")
    if rate > max_violation_rate:
        for e in all_errs[:50]:
            print(e, file=sys.stderr)
        if len(all_errs) > 50:
            print(f"... and {len(all_errs) - 50} more", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Silver-layer JSONL quality checks")
    p.add_argument("--file", type=str, default="", help="Input file (default: stdin)")
    p.add_argument("--max-violation-rate", type=float, default=0.0, help="Max allowed violation rate 0..1")
    args = p.parse_args()
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            rc = run(f, args.max_violation_rate)
    else:
        rc = run(sys.stdin, args.max_violation_rate)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
