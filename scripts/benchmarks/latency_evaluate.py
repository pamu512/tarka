#!/usr/bin/env python3
"""
Measure latency for Decision API POST /v1/decisions/evaluate (stdlib only).

Example:
  python latency_evaluate.py --url http://localhost:8000 --requests 200 --concurrency 20

For publishable benchmark posts, record hardware, compose profile, warm-up count, and seed payload.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BODY = {
    "tenant_id": "bench",
    "event_type": "payment",
    "entity_id": "bench-entity",
    "payload": {
        "amount": 2500,
        "event_count_5m": 3,
        "event_count_1h": 12,
        "event_count_24h": 40,
        "is_vpn": False,
        "hour_of_day": 14,
    },
}


def percentile(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    k = (len(sorted_ms) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_ms) - 1)
    if f == c:
        return sorted_ms[f]
    return sorted_ms[f] + (sorted_ms[c] - sorted_ms[f]) * (k - f)


def one_post(url: str, body: bytes, timeout: float) -> tuple[float, int]:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        elapsed = (time.perf_counter() - t0) * 1000.0
        return elapsed, resp.status
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return elapsed, e.code


def main() -> int:
    p = argparse.ArgumentParser(description="Benchmark Decision API evaluate latency")
    p.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL (no trailing slash)")
    p.add_argument("--requests", type=int, default=100, help="Total requests")
    p.add_argument("--concurrency", type=int, default=10, help="Concurrent workers")
    p.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    p.add_argument("--warmup", type=int, default=5, help="Warm-up requests (serial)")
    p.add_argument(
        "--payload-file",
        default="",
        help="JSON file for request body (default: built-in payment-like payload)",
    )
    args = p.parse_args()
    base = args.url.rstrip("/")
    target = f"{base}/v1/decisions/evaluate"

    if args.payload_file:
        with open(args.payload_file, encoding="utf-8") as f:
            body_obj = json.load(f)
    else:
        body_obj = DEFAULT_BODY
    body = json.dumps(body_obj).encode("utf-8")

    for _ in range(args.warmup):
        one_post(target, body, args.timeout)

    latencies: list[float] = []
    codes: list[int] = []
    errors = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(one_post, target, body, args.timeout) for _ in range(args.requests)]
        for fut in as_completed(futs):
            ms, code = fut.result()
            latencies.append(ms)
            codes.append(code)
            if code != 200:
                errors += 1

    latencies.sort()
    print(f"URL: {target}")
    print(f"requests={args.requests} concurrency={args.concurrency} errors={errors}")
    if latencies:
        print(
            f"latency_ms: min={latencies[0]:.2f} p50={percentile(latencies, 50):.2f} "
            f"p95={percentile(latencies, 95):.2f} p99={percentile(latencies, 99):.2f} "
            f"max={latencies[-1]:.2f}"
        )
        print(f"mean_ms={statistics.mean(latencies):.2f} stdev_ms={statistics.pstdev(latencies):.2f}")
    if codes:
        from collections import Counter

        print("status:", dict(Counter(codes)))
    return 1 if errors > args.requests // 2 else 0


if __name__ == "__main__":
    sys.exit(main())
