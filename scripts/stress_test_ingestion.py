#!/usr/bin/env python3
"""High-concurrency stress test for the Shadow sidecar ingestion path.

Fires **100 simultaneous** ``POST /v1/ingest`` requests that all target the same
``entity_id`` (stressing AuditLog commit + SQLAlchemy session handling in the
Shadow agent). Optional gate: after completion, query ``audit_logs`` and assert
that the **number of new rows** for that ``case_id`` equals the number of
successful Shadow-path API responses (no lost writes).

Usage:
    export ORCHESTRATOR_URL=http://127.0.0.1:8080
    export SHADOW_DATABASE_URL=postgresql+asyncpg://...   # optional gate
    uv run --extra stress python scripts/stress_test_ingestion.py

Requires ``tarka[stress]`` (``aiohttp``, ``psutil``). Postgres verification also
needs ``psycopg`` (included in the ``stress`` extra).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import psutil

# All concurrent requests share this entity_id (case_id in audit_logs).
STRESS_SHARED_ENTITY_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
TOTAL_REQUESTS = 100


@dataclass
class IngestResult:
    lane: str
    status: int
    body: str
    latency_ms: float
    parsed: dict[str, Any] | None = None


def _transaction_payload(*, entity_id: str, seq: int, lane: str) -> dict[str, Any]:
    """Build a single transaction payload (unique timestamp per request)."""
    ts = (datetime.now(UTC) + timedelta(microseconds=seq)).isoformat().replace("+00:00", "Z")
    return {
        "transaction_id": entity_id,
        "amount": 5000.0 + float(seq),
        "currency": "USD",
        "timestamp": ts,
        "metadata": {
            "stress_lane": lane,
            "stress_seq": seq,
            "stress_run": "concurrent_same_entity",
        },
    }


def _audit_count(case_id: str, database_url: str) -> int:
    """Return COUNT(*) from audit_logs for this case_id (transaction / entity id)."""
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine.url import make_url
    except ImportError as e:  # pragma: no cover - env guard
        raise RuntimeError(
            "SQLAlchemy is required for --verify-audit. Install project dependencies."
        ) from e

    u = make_url(database_url)
    if u.drivername == "postgresql+asyncpg":
        sync_url = u.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    elif u.drivername == "sqlite+aiosqlite":
        sync_url = u.set(drivername="sqlite").render_as_string(hide_password=False)
    else:
        sync_url = database_url

    if "sqlite" in sync_url and (":memory:" in sync_url or u.database in (None, "", ":memory:")):
        raise RuntimeError(
            "Cannot verify audit rows against an in-memory SQLite URL from this process; "
            "use a file-based sqlite URL or Postgres for SHADOW_DATABASE_URL."
        )

    try:
        engine = create_engine(sync_url, pool_pre_ping=True)
    except ModuleNotFoundError as e:
        if "psycopg" in str(e).lower():
            raise RuntimeError(
                "Postgres verification requires psycopg. Install with: uv sync --extra stress"
            ) from e
        raise

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM audit_logs WHERE case_id = :cid"),
            {"cid": case_id},
        ).one()
        return int(row[0])


async def _ingest_one(
    session: aiohttp.ClientSession,
    url: str,
    *,
    entity_id: str,
    seq: int,
    lane: str,
) -> IngestResult:
    payload = {"transaction": _transaction_payload(entity_id=entity_id, seq=seq, lane=lane)}
    start = time.perf_counter()
    try:
        async with session.post(
            f"{url}/v1/ingest",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            body = await resp.text()
            latency_ms = (time.perf_counter() - start) * 1000
            parsed: dict[str, Any] | None = None
            if body:
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = None
            return IngestResult(
                lane=lane,
                status=resp.status,
                body=body,
                latency_ms=latency_ms,
                parsed=parsed,
            )
    except (TimeoutError, aiohttp.ClientError) as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return IngestResult(
            lane=lane,
            status=0,
            body=str(e),
            latency_ms=latency_ms,
            parsed=None,
        )


def _is_shadow_path_success(r: IngestResult) -> bool:
    """HTTP 200 with a normal Shadow evaluation body (counts toward audit gate)."""
    if r.status != 200 or not r.parsed:
        return False
    if r.parsed.get("orchestrator_fallback_decision") is not None:
        return False
    shadow = r.parsed.get("shadow_agent")
    if not isinstance(shadow, dict):
        return False
    decision = r.parsed.get("decision")
    return decision == "SHADOW_REVIEW"


def _validate_results(results: list[IngestResult]) -> tuple[int, list[str]]:
    """Validate responses; return (shadow_success_count, error_messages)."""
    errors: list[str] = []
    shadow_ok = 0

    for i, r in enumerate(results):
        label = f"req#{i} lane={r.lane}"
        if r.status == 0:
            errors.append(f"{label}: request failed ({r.body[:200]})")
            continue
        if r.status in (500, 502):
            errors.append(f"{label}: server error {r.status}")
            continue
        if r.status != 200:
            errors.append(f"{label}: unexpected HTTP {r.status}")
            continue
        if not r.parsed:
            errors.append(f"{label}: non-JSON or empty body")
            continue

        if _is_shadow_path_success(r):
            shadow_ok += 1
            reasoning = r.parsed.get("shadow_agent", {}).get("reasoning")
            if not isinstance(reasoning, list) or not reasoning:
                errors.append(f"{label}: missing shadow_agent.reasoning list")
        else:
            fb = r.parsed.get("orchestrator_fallback_decision")
            if fb is not None:
                errors.append(
                    f"{label}: orchestrator fallback ({fb}); excluded from shadow audit gate"
                )
            else:
                errors.append(
                    f"{label}: expected SHADOW_REVIEW + shadow_agent, got decision="
                    f"{r.parsed.get('decision')!r}"
                )

    return shadow_ok, errors


async def _run_stress(
    orchestrator_url: str,
    *,
    entity_id: str,
    total: int,
    verify_audit: bool,
    database_url: str | None,
) -> int:
    """Run concurrent ingests; return process exit code (0 = success)."""
    proc = psutil.Process()
    mem_before = proc.memory_info().rss / 1024 / 1024

    baseline_audit: int | None = None
    if verify_audit:
        if not database_url:
            print("ERROR: --verify-audit requires SHADOW_DATABASE_URL or --shadow-database-url")
            return 2
        try:
            baseline_audit = _audit_count(entity_id, database_url)
            print(f"Baseline audit_logs for case_id={entity_id}: {baseline_audit}")
        except Exception as e:
            print(f"ERROR: failed to read baseline audit count: {e}")
            return 2

    connector = aiohttp.TCPConnector(limit=max(128, total + 8))
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(
                _ingest_one(
                    session,
                    orchestrator_url,
                    entity_id=entity_id,
                    seq=seq,
                    lane="shadow",
                )
            )
            for seq in range(total)
        ]
        results = await asyncio.gather(*tasks)

    mem_after = proc.memory_info().rss / 1024 / 1024
    print(f"Memory: {mem_before:.1f} MB -> {mem_after:.1f} MB (delta {mem_after - mem_before:+.1f} MB)")

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p99 = latencies[int(len(latencies) * 0.99)] if len(latencies) >= 2 else latencies[-1]
        print(f"Latency p50={p50:.1f}ms p99={p99:.1f}ms max={max(latencies):.1f}ms")

    shadow_ok, errors = _validate_results(results)
    print(f"Shadow-path successes (gate numerator): {shadow_ok}/{total}")

    for msg in errors[:20]:
        print(f"  {msg}")
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more errors")

    if errors:
        print("FAIL: validation errors above")
        return 1

    if verify_audit and database_url is not None and baseline_audit is not None:
        try:
            after = _audit_count(entity_id, database_url)
        except Exception as e:
            print(f"ERROR: post-run audit count failed: {e}")
            return 2
        new_rows = after - baseline_audit
        print(f"Post-run audit_logs for case_id={entity_id}: {after} (new rows: {new_rows})")
        if new_rows != shadow_ok:
            print(
                f"FAIL: audit gate — new AuditLog rows ({new_rows}) != successful shadow responses ({shadow_ok})"
            )
            return 1
        print("PASS: audit gate — new AuditLog rows match successful shadow API responses")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--orchestrator-url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8080"),
        help="Orchestrator base URL",
    )
    parser.add_argument(
        "--entity-id",
        default=STRESS_SHARED_ENTITY_ID,
        help="Shared transaction_id / entity_id for all concurrent requests",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=TOTAL_REQUESTS,
        help="Number of concurrent ingest requests",
    )
    parser.add_argument(
        "--verify-audit",
        action="store_true",
        help="After run, COUNT(audit_logs) delta must equal successful shadow responses",
    )
    parser.add_argument(
        "--shadow-database-url",
        default=os.environ.get("SHADOW_DATABASE_URL"),
        help="Shadow DB URL for audit verification (or set SHADOW_DATABASE_URL)",
    )
    parser.add_argument(
        "--skip-audit-verify",
        action="store_true",
        help="Do not query audit_logs even if SHADOW_DATABASE_URL is set",
    )
    args = parser.parse_args()

    has_db = bool(args.shadow_database_url)
    if args.verify_audit and not has_db:
        parser.error("--verify-audit requires --shadow-database-url or SHADOW_DATABASE_URL")
    verify = (args.verify_audit or has_db) and not args.skip_audit_verify
    return asyncio.run(
        _run_stress(
            args.orchestrator_url.rstrip("/"),
            entity_id=args.entity_id,
            total=args.total,
            verify_audit=verify,
            database_url=args.shadow_database_url,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
