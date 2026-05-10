#!/usr/bin/env python3
"""Async concurrent load against the v2 Orchestrator ``POST /v1/ingest`` (Prompt 59).

Fires **100 simultaneous** requests via ``asyncio`` + ``httpx``:
  * **30%** payloads that stay on the implicit-allow path (no demo rule match),
  * **40%** that hit the demo **BLOCK** lane (``metadata`` contains ``STRESS_BLOCK_LANE``),
  * **30%** that hit **SHADOW_REVIEW** at the rule engine (``amount`` > 100; Orchestrator may
    call Shadow if ``SHADOW_AGENT_URL`` is configured).

This script **does not** observe OS swap or OOM from inside Python; pair it with ``vmstat`` /
host memory metrics if you need proof the kernel did not thrash. It **does** prove the client
stack completes without unhandled exceptions and surfaces tail latency.

Gate: logs **p95** and **p99** (milliseconds) overall and per cohort. If **p99 latency for BLOCK
cohort** (HTTP 200 only) exceeds **50 ms**, prints ``PERFORMANCE_REGRESSION`` and exits **1**.

Usage::

    export ORCHESTRATOR_URL=http://127.0.0.1:8790/v1/ingest
    # SHADOW cohort needs ``SHADOW_AGENT_URL`` on the Orchestrator. If the sidecar is down, the
    # Orchestrator should return **200** with ``FLAG`` + ``SIDECAR_UNREACHABLE`` (see
    # ``scripts/run_shadow_dead_letter_gate.py``).
    export SHADOW_AGENT_URL=http://127.0.0.1:8801   # optional
    python3 scripts/bench_ingestion.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

TOTAL = 100
ALLOW_END = 30
BLOCK_END = 70  # 30 + 40


def _percentile_ms(values: list[float], p: float) -> float:
    """Nearest-rank / linear interpolation between closest ranks; ``p`` in [0, 100]."""
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return float("nan")
    if n == 1:
        return xs[0]
    rank = (p / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (rank - lo)


def _cohort_for_index(i: int) -> str:
    if i < ALLOW_END:
        return "allow"
    if i < BLOCK_END:
        return "block"
    return "shadow"


def _payload_for_index(i: int) -> dict[str, Any]:
    """Build ``TransactionSchema`` JSON for orchestrator ``POST /v1/ingest``."""
    ts = (datetime.now(UTC) + timedelta(microseconds=i)).isoformat()
    entity_id = str(uuid4())
    cohort = _cohort_for_index(i)
    if cohort == "allow":
        return {
            "entity_id": entity_id,
            "amount": 10.0,
            "timestamp": ts,
            "metadata": {"bench": "allow", "seq": i},
        }
    if cohort == "block":
        return {
            "entity_id": entity_id,
            "amount": 10.0,
            "timestamp": ts,
            "metadata": {"lane": "STRESS_BLOCK_LANE", "bench": "block", "seq": i},
        }
    return {
        "entity_id": entity_id,
        "amount": 500.0,
        "timestamp": ts,
        "metadata": {"bench": "shadow", "seq": i},
    }


@dataclass
class BenchRow:
    cohort: str
    status_code: int
    latency_ms: float
    error: str | None


async def _one_ingest(
    client: httpx.AsyncClient,
    url: str,
    idx: int,
) -> BenchRow:
    cohort = _cohort_for_index(idx)
    payload = _payload_for_index(idx)
    t0 = time.perf_counter()
    try:
        r = await client.post(url, json=payload)
        ms = (time.perf_counter() - t0) * 1000.0
        return BenchRow(cohort, r.status_code, ms, None)
    except Exception as exc:  # pragma: no cover - defensive for bench runs
        ms = (time.perf_counter() - t0) * 1000.0
        return BenchRow(cohort, 0, ms, str(exc))


async def _run_all(url: str) -> list[BenchRow]:
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=0)
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        tasks = [_one_ingest(client, url, i) for i in range(TOTAL)]
        return await asyncio.gather(*tasks)


def _print_stats(label: str, latencies_ms: list[float]) -> None:
    if not latencies_ms:
        print(f"  {label}: (no samples)")
        return
    p50 = _percentile_ms(latencies_ms, 50)
    p95 = _percentile_ms(latencies_ms, 95)
    p99 = _percentile_ms(latencies_ms, 99)
    print(f"  {label}: n={len(latencies_ms)}  p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms")


def main() -> int:
    parser = argparse.ArgumentParser(description="Concurrent orchestrator ingest benchmark.")
    parser.add_argument(
        "--url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8790/v1/ingest"),
        help="Orchestrator ingest URL (default: env ORCHESTRATOR_URL or http://127.0.0.1:8790/v1/ingest)",
    )
    args = parser.parse_args()
    url: str = args.url

    print(f"Bench: {TOTAL} concurrent POST {url}")
    print("Mix: 30% allow-path, 40% BLOCK lane, 30% SHADOW_REVIEW (amount>100)")
    print(
        "Note: swap/OOM proof requires OS-level monitoring; this bench measures HTTP stability + latency."
    )

    t_wall0 = time.perf_counter()
    rows = asyncio.run(_run_all(url))
    wall_s = time.perf_counter() - t_wall0

    ok = [r for r in rows if r.error is None and 200 <= r.status_code < 300]
    fail = [r for r in rows if r.error is not None or r.status_code < 200 or r.status_code >= 300]
    print(f"Wall-clock (gather): {wall_s:.3f}s  OK={len(ok)}  FAIL={len(fail)}")

    all_ms = [r.latency_ms for r in ok]
    _print_stats("overall (2xx)", all_ms)

    for cohort in ("allow", "block", "shadow"):
        ms = [r.latency_ms for r in ok if r.cohort == cohort]
        _print_stats(f"cohort={cohort} (2xx)", ms)

    block_ok_ms = [r.latency_ms for r in ok if r.cohort == "block"]
    if len(block_ok_ms) == 0:
        print(
            "ERROR: no successful BLOCK cohort responses; cannot evaluate p99 gate.",
            file=sys.stderr,
        )
        return 2
    p95_block = _percentile_ms(block_ok_ms, 95)
    p99_block = _percentile_ms(block_ok_ms, 99)
    print(f"BLOCK cohort gate — p95={p95_block:.2f}ms  p99={p99_block:.2f}ms  threshold_p99=50ms")

    regression = not math.isnan(p99_block) and p99_block > 50.0
    if regression:
        print(
            "PERFORMANCE_REGRESSION: p99 for Rule Engine (BLOCK) cohort exceeds 50ms",
            file=sys.stderr,
        )
        return 1
    if fail:
        print(
            "WARN: some requests failed (Shadow URL missing → 503 on shadow cohort is common).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
