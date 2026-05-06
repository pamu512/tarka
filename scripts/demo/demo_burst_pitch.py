#!/usr/bin/env python3
"""Deterministic investor pitch: POST core-api demo-burst (50 evaluates → OSINT → block → SAR).

Strict sequence is enforced server-side. Default budget < 45s when Redis, decision, case, and
(optional) integration-ingress are healthy on localhost.

Usage::

    export TARKA_DEMO_BURST_TOKEN="$(openssl rand -hex 16)"
    export API_KEYS="your-key"
    # optional: export DEMO_BURST_INGRESS_URL=http://127.0.0.1:8003

    python scripts/demo/demo_burst_pitch.py \\
        --base-url http://127.0.0.1:8000 \\
        --api-key "$API_KEYS"

Or via Vite (if ``/api/v1/internal/demo-burst`` proxy is configured)::

    python scripts/demo/demo_burst_pitch.py --base-url http://127.0.0.1:3000 --path-prefix /api/v1/internal
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--base-url", default=os.environ.get("CORE_API_URL", "http://127.0.0.1:8000").rstrip("/")
    )
    p.add_argument(
        "--path-prefix",
        default="",
        help="Optional URL prefix before /demo-burst, e.g. /api/v1/internal for a gateway rewrite.",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY", os.environ.get("API_KEYS", "").split(",")[0].strip()),
    )
    p.add_argument(
        "--demo-token",
        default=os.environ.get("TARKA_DEMO_BURST_TOKEN", "").strip(),
        help="Defaults to TARKA_DEMO_BURST_TOKEN env.",
    )
    p.add_argument(
        "--timeout", type=float, default=44.0, help="HTTP client timeout seconds (keep under 45)."
    )
    args = p.parse_args()

    token = (args.demo_token or "").strip()
    if not token:
        print("error: set TARKA_DEMO_BURST_TOKEN or pass --demo-token", file=sys.stderr)
        return 2
    api_key = (args.api_key or "").strip()
    if not api_key:
        print("error: pass --api-key or set API_KEY / API_KEYS", file=sys.stderr)
        return 2

    prefix = (args.path_prefix or "").rstrip("/")
    path = f"{prefix}/demo-burst" if prefix else "/v1/internal/demo-burst"
    if not path.startswith("/"):
        path = "/" + path
    url = f"{args.base_url}{path}"

    try:
        import httpx
    except ImportError:
        print("error: install httpx (pip install httpx)", file=sys.stderr)
        return 3

    headers = {
        "x-api-key": api_key,
        "x-tarka-demo-burst-token": token,
        "accept": "application/json",
    }
    t0 = time.perf_counter()
    with httpx.Client(timeout=args.timeout) as client:
        r = client.post(url, headers=headers)
    elapsed = time.perf_counter() - t0
    print(f"HTTP {r.status_code} in {elapsed:.2f}s — {url}")
    try:
        body = r.json()
    except Exception:
        print(r.text[:4000])
        return 1 if r.status_code >= 400 else 0
    print(json.dumps(body, indent=2, default=str))
    if r.status_code >= 400:
        return 1
    total_ms = body.get("elapsed_ms_total")
    if isinstance(total_ms, int) and total_ms > 45_000:
        print(
            f"warning: server-reported total {total_ms}ms exceeds 45s pitch budget", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
