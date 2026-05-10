#!/usr/bin/env python3
"""Baseline load test: 5,000 concurrent POSTs to /v1/decide and PostgreSQL audit row verification.

Requires:
  - Running API (e.g. uvicorn) reachable at LOAD_TEST_BASE_URL (default http://127.0.0.1:8000).
  - DATABASE_URL pointing at the same PostgreSQL database the API uses (postgresql+asyncpg://...).
  - Dependencies: pip install aiohttp asyncpg

Usage:
  export DATABASE_URL='postgresql+asyncpg://user:pass@127.0.0.1:5432/dbname'
  python scripts/load_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
import asyncpg

TOTAL_REQUESTS = 5000


def _payload(seq: int) -> dict[str, Any]:
    return {
        "entity_id": str(uuid.uuid4()),
        "amount": 100.0 + (seq % 97) * 0.001,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {"load_test_seq": seq, "bench": "baseline_tps"},
    }


def _asyncpg_dsn_from_sqlalchemy(url: str) -> str:
    """Strip SQLAlchemy async driver prefix so asyncpg accepts the DSN."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.split("postgresql+asyncpg://", 1)[1]
    if url.startswith("postgres+asyncpg://"):
        return "postgres://" + url.split("postgres+asyncpg://", 1)[1]
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return url
    raise ValueError(
        "DATABASE_URL must be a PostgreSQL URL (e.g. postgresql+asyncpg://user:pass@host/db)",
    )


async def _audit_log_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) AS c FROM audit_logs")
        if row is None:
            return 0
        return int(row["c"])


async def _post_decide(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict[str, Any],
) -> int:
    async with session.post(url, json=payload) as resp:
        await resp.read()
        return resp.status


async def _run() -> None:
    base_url = os.environ.get("LOAD_TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    endpoint = f"{base_url}/v1/decide"

    db_url_raw = os.environ.get("DATABASE_URL", "").strip()
    if not db_url_raw:
        print("ERROR: DATABASE_URL must be set to the API's PostgreSQL database.", file=sys.stderr)
        raise SystemExit(2)

    dsn = _asyncpg_dsn_from_sqlalchemy(db_url_raw)

    payloads = [_payload(i) for i in range(TOTAL_REQUESTS)]

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=min(32, TOTAL_REQUESTS))
    try:
        count_before = await _audit_log_count(pool)

        connector = aiohttp.TCPConnector(limit=TOTAL_REQUESTS, limit_per_host=TOTAL_REQUESTS)
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300)

        started = time.perf_counter()
        statuses: list[int] = []

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [_post_decide(session, endpoint, p) for p in payloads]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.perf_counter() - started

        for r in results:
            if isinstance(r, Exception):
                print(f"ERROR: request failed: {r!r}", file=sys.stderr)
                raise SystemExit(1)
            statuses.append(int(r))

        ok_200 = sum(1 for s in statuses if s == 200)
        non_200 = TOTAL_REQUESTS - ok_200

        count_after = await _audit_log_count(pool)
    finally:
        await pool.close()

    delta_rows = count_after - count_before

    rps = TOTAL_REQUESTS / elapsed if elapsed > 0 else float("inf")

    print(f"endpoint          : {endpoint}")
    print(f"total_requests    : {TOTAL_REQUESTS}")
    print(f"elapsed_seconds   : {elapsed:.6f}")
    print(f"requests_per_sec  : {rps:.6f}")
    print(f"http_200          : {ok_200}")
    print(f"http_non_200      : {non_200}")
    print(f"audit_rows_before : {count_before}")
    print(f"audit_rows_after  : {count_after}")
    print(f"audit_rows_delta  : {delta_rows}")

    if delta_rows != TOTAL_REQUESTS:
        print(
            f"FAILED: expected exactly {TOTAL_REQUESTS} new audit_logs rows, got {delta_rows}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if ok_200 != TOTAL_REQUESTS:
        print(
            f"FAILED: expected {TOTAL_REQUESTS} HTTP 200 responses, got {ok_200}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("OK: baseline TPS run verified (5000 requests, 5000 committed audit rows).")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
