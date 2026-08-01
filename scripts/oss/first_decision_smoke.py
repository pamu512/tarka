#!/usr/bin/env python3
"""OSS 15-minute path: health + evaluate on Tarka Lite (no ingest profile required).

Usage (repo root, stack already up)::

  python3 scripts/oss/first_decision_smoke.py

Env overrides: DECISION_API (default http://127.0.0.1:8000/decisions), API_KEY / x-api-key.
See docs/docs/guides/oss-15-minute-first-decision.md
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    headers = {"accept": "application/json"}
    data = None
    if payload is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        print(f"[fail] connect {url}: {exc}", file=sys.stderr)
        return 0, str(exc)


def main() -> int:
    base = os.environ.get("DECISION_API", "http://127.0.0.1:8000/decisions").rstrip("/")
    key = (os.environ.get("API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip() or None

    st, health = _request("GET", f"{base}/v1/health", api_key=key, timeout=15.0)
    if st != 200:
        print(f"[fail] health GET {base}/v1/health -> {st} {health!r}", file=sys.stderr)
        print(
            "Hint: start Lite — see docs/docs/guides/oss-15-minute-first-decision.md",
            file=sys.stderr,
        )
        return 1
    print("[ok] decision-api health")

    body = {
        "tenant_id": "demo",
        "entity_id": "oss-15min-user",
        "event_type": "payment",
        "payload": {
            "amount": 42.0,
            "currency": "USD",
            "channel": "card_not_present",
        },
    }
    st, out = _request(
        "POST",
        f"{base}/v1/decisions/evaluate",
        payload=body,
        api_key=key,
    )
    if st != 200 or not isinstance(out, dict):
        print(f"[fail] evaluate status={st} body={out!r}", file=sys.stderr)
        if st in (401, 403):
            print(
                "Hint: set ALLOW_INSECURE_NO_AUTH=true in infra/deploy/.env for local try-it "
                "(or pass API_KEY).",
                file=sys.stderr,
            )
        return 1

    trace = out.get("trace_id")
    decision = out.get("decision")
    score = out.get("score")
    if not trace:
        print(f"[fail] evaluate missing trace_id: {out!r}", file=sys.stderr)
        return 1

    print(f"[ok] evaluate decision={decision} score={score} trace_id={trace}")

    # Best-effort audit fetch (not required for pass).
    st_a, audit = _request("GET", f"{base}/v1/audit/{trace}", api_key=key, timeout=15.0)
    if st_a == 200 and isinstance(audit, dict):
        print(f"[ok] audit fetch keys={sorted(audit.keys())[:8]}")
    else:
        print(f"[warn] audit GET skipped/unavailable status={st_a}")

    print("OSS 15-minute first decision: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
