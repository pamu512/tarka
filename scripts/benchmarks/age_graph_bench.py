#!/usr/bin/env python3
"""Lightweight Apache AGE / Postgres graph latency probe (CQRS planning).

Requires: psycopg[binary], AGE extension installed, connection string in DATABASE_URL.

Example::

  DATABASE_URL=postgresql://user:pass@localhost:5432/fraud \\
    python3 scripts/benchmarks/age_graph_bench.py --repeat 50
"""
from __future__ import annotations

import argparse
import os
import statistics
import time


def main() -> None:
    p = argparse.ArgumentParser(description="AGE graph micro-benchmark")
    p.add_argument("--repeat", type=int, default=30)
    p.add_argument(
        "--sql",
        default="SELECT * FROM cypher('fraud_graph', $$ MATCH (n:Account) RETURN id(n) LIMIT 5 $$) as (id agtype);",
    )
    args = p.parse_args()
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("Set DATABASE_URL (sync psycopg DSN) to run this benchmark.")
        raise SystemExit(0)
    try:
        import psycopg
    except ImportError:
        print("Install psycopg: pip install 'psycopg[binary]'")
        raise SystemExit(1)

    lat: list[float] = []
    with psycopg.connect(dsn) as conn:
        conn.execute("LOAD 'age';")
        conn.execute("SET search_path = ag_catalog, '$user', public;")
        for _ in range(args.repeat):
            t0 = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute(args.sql)
                cur.fetchall()
            lat.append((time.perf_counter() - t0) * 1000.0)

    print(f"runs={args.repeat} p50_ms={statistics.median(lat):.3f} p95_ms={statistics.quantiles(lat, n=20)[18]:.3f}")


if __name__ == "__main__":
    main()
