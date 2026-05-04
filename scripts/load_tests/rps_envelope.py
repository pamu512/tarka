#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from simple_load_test import run_load


async def run_envelope(
    base_url: str,
    api_key: str | None,
    duration_seconds: int,
    concurrencies: list[int],
    pace_ms: int,
    max_failure_rate: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    best_safe: dict[str, Any] | None = None

    for c in concurrencies:
        result = await run_load(
            base_url,
            duration_seconds,
            c,
            api_key=api_key,
            pace_ms=pace_ms,
        )
        row = {
            "concurrency": c,
            "success_rps": result["success_rps"],
            "failure_rate": result["failure_rate"],
            "p95_ms": result["p95_ms"],
            "status_counts": result["status_counts"],
        }
        rows.append(row)
        if row["failure_rate"] <= max_failure_rate:
            if best_safe is None or row["success_rps"] > best_safe["success_rps"]:
                best_safe = row

    return {
        "base_url": base_url,
        "duration_seconds_per_step": duration_seconds,
        "pace_ms": pace_ms,
        "max_failure_rate": max_failure_rate,
        "rows": rows,
        "best_safe": best_safe,
    }


def _parse_concurrency_csv(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        out.append(max(1, int(p)))
    return out or [10, 20, 40, 80]


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure max-safe success RPS envelope for decision-api.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--concurrency", default="10,20,40,80,120,160")
    parser.add_argument("--pace-ms", type=int, default=0)
    parser.add_argument("--max-failure-rate", type=float, default=0.01)
    args = parser.parse_args()

    concurrencies = _parse_concurrency_csv(args.concurrency)
    result = asyncio.run(
        run_envelope(
            args.base_url,
            args.api_key,
            max(1, args.duration_seconds),
            concurrencies,
            max(0, args.pace_ms),
            max(0.0, min(1.0, args.max_failure_rate)),
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
