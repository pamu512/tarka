#!/usr/bin/env python3
from __future__ import annotations

"""
Compare aggregate sorted-set keys between two Redis instances (e.g. production vs scratch replay DB).

Requires: pip install redis
Usage:
  python scripts/replay/diff_aggregate_redis.py \\
    --left-url redis://localhost:6379/0 --right-url redis://localhost:6379/15
"""


import argparse
import sys
from typing import Any

try:
    import redis
except ImportError:
    print("Install redis: pip install redis", file=sys.stderr)
    raise SystemExit(2)


def zset_snapshot(r: redis.Redis, pattern: str) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for key in r.scan_iter(match=pattern, count=500):
        if r.type(key) != "zset":
            continue
        pairs = r.zrange(key, 0, -1, withscores=True)
        out[key] = sorted((str(m), float(s)) for m, s in pairs)
    return out


def diff_snapshots(
    left: dict[str, list[tuple[str, float]]],
    right: dict[str, list[tuple[str, float]]],
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    all_keys = sorted(set(left) | set(right))
    for k in all_keys:
        a, b = left.get(k), right.get(k)
        if a is None:
            diffs.append({"key": k, "kind": "only_right", "right_zcard": len(b or [])})
        elif b is None:
            diffs.append({"key": k, "kind": "only_left", "left_zcard": len(a)})
        elif a != b:
            diffs.append(
                {
                    "key": k,
                    "kind": "mismatch",
                    "left_pairs": len(a),
                    "right_pairs": len(b),
                }
            )
    return diffs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diff fraud aggregate ZSETs between two Redis URLs.")
    p.add_argument("--left-url", required=True, help="First Redis (e.g. production)")
    p.add_argument("--right-url", required=True, help="Second Redis (e.g. scratch replay DB)")
    p.add_argument(
        "--pattern",
        default="fraud:agg*",
        help="SCAN match pattern (default: fraud:agg* includes aggval keys)",
    )
    args = p.parse_args(argv)

    r1 = redis.from_url(args.left_url, decode_responses=True)
    r2 = redis.from_url(args.right_url, decode_responses=True)
    try:
        snap_l = zset_snapshot(r1, args.pattern)
        snap_r = zset_snapshot(r2, args.pattern)
    finally:
        r1.close()
        r2.close()

    diffs = diff_snapshots(snap_l, snap_r)
    if not diffs:
        print(f"No differences for pattern {args.pattern!r} ({len(snap_l)} keys left, {len(snap_r)} keys right).")
        return 0

    print(f"Found {len(diffs)} difference(s) for pattern {args.pattern!r}:")
    for d in diffs:
        print(d)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
