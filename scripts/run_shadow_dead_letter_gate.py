#!/usr/bin/env python3
"""Gate: ``kill -9`` Shadow sidecar mid-load → every ``SHADOW_REVIEW`` ingest returns **200** + dead-letter.

Expects a running stack: Rule Engine, Orchestrator (with ``SHADOW_AGENT_URL``), and Shadow listening on
the URL you pass. The script finds listener PIDs on the Shadow TCP port, sends **SIGKILL**, then
fires **N** concurrent ``POST /v1/ingest`` payloads that trigger ``SHADOW_REVIEW`` (``amount`` > 100).

Pass criteria: **100%** HTTP **200**, ``orchestrator_fallback_decision`` == ``FLAG``, and
``orchestrator_fallback_reason`` == ``SIDECAR_UNREACHABLE``.

Optional ``--with-bench-subprocess`` starts ``scripts/bench_ingestion.py`` in the background before
the kill so load overlaps the outage (assertions still apply only to this script's N requests).

Usage::

    export ORCHESTRATOR_URL=http://127.0.0.1:8790/v1/ingest
    export SHADOW_AGENT_URL=http://127.0.0.1:8801
    python3 scripts/run_shadow_dead_letter_gate.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def _shadow_port(shadow_url: str) -> int:
    u = urlparse(shadow_url)
    if u.port is not None:
        return int(u.port)
    if u.scheme == "https":
        return 443
    return 80


def _port_has_tcp_listener(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _listening_pids(port: int) -> list[int]:
    """Return PIDs with a TCP LISTEN socket on ``port`` (macOS/Linux ``lsof``)."""
    cp = subprocess.run(
        ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0 or not cp.stdout.strip():
        return []
    out: list[int] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return sorted(set(out))


def _kill_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue


def _payload(seq: int) -> dict:
    ts = (datetime.now(UTC) + timedelta(microseconds=seq)).isoformat()
    return {
        "entity_id": str(uuid4()),
        "amount": 500.0,
        "timestamp": ts,
        "metadata": {"dead_letter_gate": True, "seq": seq},
    }


async def _burst(url: str, n: int) -> list[httpx.Response]:
    limits = httpx.Limits(max_connections=max(n + 10, 32), max_keepalive_connections=0)
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        tasks = [client.post(url, json=_payload(i)) for i in range(n)]
        return await asyncio.gather(*tasks)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dead-letter gate: kill Shadow, assert 200 + FLAG.")
    ap.add_argument(
        "--orchestrator-url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8790/v1/ingest"),
    )
    ap.add_argument(
        "--shadow-url",
        default=os.environ.get("SHADOW_AGENT_URL", "").strip(),
        help="Shadow base URL (default: env SHADOW_AGENT_URL)",
    )
    ap.add_argument("--n", type=int, default=100, help="Concurrent SHADOW_REVIEW ingests after kill")
    ap.add_argument(
        "--with-bench-subprocess",
        action="store_true",
        help="Run scripts/bench_ingestion.py in background before SIGKILL (needs ORCHESTRATOR_URL)",
    )
    args = ap.parse_args()

    if not args.shadow_url:
        print("ERROR: set SHADOW_AGENT_URL or pass --shadow-url", file=sys.stderr)
        return 2

    parsed = urlparse(args.shadow_url)
    host = parsed.hostname or "127.0.0.1"
    port = _shadow_port(args.shadow_url)

    if not _port_has_tcp_listener(host, port):
        print(f"ERROR: nothing listening on {host}:{port} (start Shadow first)", file=sys.stderr)
        return 2

    pids = _listening_pids(port)
    if not pids:
        print(
            f"ERROR: could not resolve listener PIDs on port {port} (install ``lsof`` or check URL)",
            file=sys.stderr,
        )
        return 2

    repo = Path(__file__).resolve().parents[1]
    bench: subprocess.Popen[bytes] | None = None
    if args.with_bench_subprocess:
        bench = subprocess.Popen(
            [sys.executable, str(repo / "scripts" / "bench_ingestion.py")],
            cwd=str(repo),
            env={**os.environ},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.25)

    print(f"SIGKILL Shadow listener PIDs on port {port}: {pids}", flush=True)
    _kill_pids(pids)
    time.sleep(0.05)

    responses = asyncio.run(_burst(args.orchestrator_url, args.n))

    if bench is not None:
        try:
            bench.wait(timeout=120)
        except subprocess.TimeoutExpired:
            bench.kill()

    bad: list[str] = []
    for i, r in enumerate(responses):
        if r.status_code != 200:
            bad.append(f"idx={i} status={r.status_code} body={r.text[:200]!r}")
            continue
        try:
            data = r.json()
        except Exception as exc:  # pragma: no cover
            bad.append(f"idx={i} non-json: {exc}")
            continue
        if data.get("orchestrator_fallback_decision") != "FLAG":
            bad.append(f"idx={i} missing FLAG fallback: {data!r}")
            continue
        if data.get("orchestrator_fallback_reason") != "SIDECAR_UNREACHABLE":
            bad.append(f"idx={i} reason={data.get('orchestrator_fallback_reason')!r}")
            continue

    if bad:
        print(f"GATE_FAIL: {len(bad)} / {args.n} responses failed checks", file=sys.stderr)
        for line in bad[:12]:
            print(line, file=sys.stderr)
        if len(bad) > 12:
            print(f"... and {len(bad) - 12} more", file=sys.stderr)
        return 1

    print(f"GATE_OK: {args.n}/{args.n} HTTP 200 + FLAG + SIDECAR_UNREACHABLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
