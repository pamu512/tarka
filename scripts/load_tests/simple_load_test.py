#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import time
from statistics import mean
from typing import Any

import httpx


async def run_once(client: httpx.AsyncClient, url: str, idx: int, *, api_key: str | None = None) -> tuple[bool, float, int | None]:
    payload = {
        "tenant_id": "loadtest",
        "entity_id": f"entity-{idx%1000}",
        "event_type": "login",
        "payload": {"amount": 10.0, "currency": "USD"},
    }
    t0 = time.perf_counter()
    try:
        headers = {"x-api-key": api_key} if api_key else None
        r = await client.post(url, json=payload, headers=headers)
        ok = r.status_code == 200
        status = r.status_code
    except Exception:
        ok = False
        status = None
    dt = (time.perf_counter() - t0) * 1000.0
    return ok, dt, status


async def run_load(
    base_url: str,
    duration: int,
    concurrency: int,
    *,
    api_key: str | None = None,
    pace_ms: int = 0,
) -> dict:
    url = f"{base_url.rstrip('/')}/v1/decisions/evaluate"
    timeout = httpx.Timeout(10.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        latencies: list[float] = []
        ok = 0
        fail = 0
        status_counts: dict[str, int] = {}
        stop_at = time.time() + duration
        sem = asyncio.Semaphore(concurrency)

        async def worker(i: int) -> None:
            nonlocal ok, fail
            while time.time() < stop_at:
                async with sem:
                    success, dt, status = await run_once(client, url, i, api_key=api_key)
                latencies.append(dt)
                if success:
                    ok += 1
                else:
                    fail += 1
                status_key = str(status) if status is not None else "network_error"
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                if pace_ms > 0:
                    await asyncio.sleep(max(0.0, pace_ms / 1000.0))

        tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
        await asyncio.gather(*tasks)

    total = ok + fail
    return {
        "requests_total": total,
        "success": ok,
        "failures": fail,
        "rps": round(total / max(duration, 1), 2),
        "success_rps": round(ok / max(duration, 1), 2),
        "failure_rate": round(fail / max(total, 1), 4),
        "status_counts": dict(sorted(status_counts.items())),
        "p50_ms": round(sorted(latencies)[int(len(latencies) * 0.50)], 2) if latencies else None,
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 2) if latencies else None,
        "avg_ms": round(mean(latencies), 2) if latencies else None,
    }


async def run_profile(
    base_url: str,
    sustained_duration: int,
    sustained_concurrency: int,
    burst_duration: int,
    burst_concurrency: int,
    *,
    api_key: str | None = None,
    pace_ms: int = 0,
) -> dict[str, Any]:
    sustained = await run_load(base_url, sustained_duration, sustained_concurrency, api_key=api_key, pace_ms=pace_ms)
    burst = await run_load(base_url, burst_duration, burst_concurrency, api_key=api_key, pace_ms=pace_ms)
    return {"sustained": sustained, "burst": burst}


def main() -> int:
    p = argparse.ArgumentParser(description="Simple load test for decision-api.")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--api-key", default=None)
    p.add_argument("--pace-ms", type=int, default=0, help="Sleep after each request per worker.")
    p.add_argument("--duration-seconds", type=int, default=60, help="Custom single-run duration.")
    p.add_argument("--concurrency", type=int, default=100, help="Custom single-run concurrency.")
    p.add_argument("--profile", action="store_true", help="Run sustained + burst profile.")
    p.add_argument("--sustained-duration-seconds", type=int, default=300)
    p.add_argument("--sustained-concurrency", type=int, default=400)
    p.add_argument("--burst-duration-seconds", type=int, default=300)
    p.add_argument("--burst-concurrency", type=int, default=1500)
    p.add_argument("--target-rps-sustained", type=float, default=1000.0)
    p.add_argument("--target-rps-burst", type=float, default=5000.0)
    args = p.parse_args()
    if args.profile:
        result = asyncio.run(
            run_profile(
                args.base_url,
                args.sustained_duration_seconds,
                args.sustained_concurrency,
                args.burst_duration_seconds,
                args.burst_concurrency,
                api_key=args.api_key,
                pace_ms=args.pace_ms,
            )
        )
        sustained = result["sustained"]
        burst = result["burst"]
        targets = {
            "target_rps_sustained": args.target_rps_sustained,
            "target_rps_burst": args.target_rps_burst,
            "sustained_met": sustained["rps"] >= args.target_rps_sustained,
            "burst_met": burst["rps"] >= args.target_rps_burst,
        }
        result["targets"] = targets
        print(json.dumps(result, indent=2))
        return 0 if sustained["failures"] == 0 and burst["failures"] == 0 else 1

    result = asyncio.run(
        run_load(
            args.base_url,
            args.duration_seconds,
            args.concurrency,
            api_key=args.api_key,
            pace_ms=args.pace_ms,
        )
    )
    print(json.dumps(result, indent=2))
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

