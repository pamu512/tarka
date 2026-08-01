#!/usr/bin/env python3
"""Demo: location-service co-presence → features rules can consume.

Usage (repo root, location-service or Lite stack up)::

  python3 scripts/oss/copresence_demo.py

Env:
  LOCATION_API — default http://127.0.0.1:8000/location (Lite via core-api)
                or http://127.0.0.1:8004 for a direct location-service bind
  API_KEY / DEMO_API_KEY — optional x-api-key

See docs/docs/guides/location-context-and-trusted-places.md
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
    base = os.environ.get("LOCATION_API", "http://127.0.0.1:8000/location").rstrip("/")
    key = (os.environ.get("API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip() or None

    st, health = _request("GET", f"{base}/v1/health", api_key=key, timeout=15.0)
    if st != 200:
        print(f"[fail] health GET {base}/v1/health -> {st} {health!r}", file=sys.stderr)
        print(
            "Hint: start Lite (docker compose -f infra/deploy/docker-compose.lite.yml) "
            "or point LOCATION_API at a running location-service.",
            file=sys.stderr,
        )
        return 1
    print("[ok] location-service health")

    # Multi-session feature drives _copresence_risk (>1 distinct session → risk > 0).
    body = {
        "tenant_id": "demo",
        "entity_id": "copresence-demo-user",
        "current": {"lat": 37.775, "lon": -122.419, "ts": 1_700_000_000, "source": "gps"},
        "previous": {"lat": 37.774, "lon": -122.418, "ts": 1_699_999_000, "source": "gps"},
        "features": {"distinct_session_id_24h": 4},
    }
    st, out = _request("POST", f"{base}/v1/evaluate", payload=body, api_key=key)
    if st != 200 or not isinstance(out, dict):
        print(f"[fail] evaluate status={st} body={out!r}", file=sys.stderr)
        return 1

    copresence = float(out.get("copresence_risk") or 0)
    travel = float(out.get("impossible_travel_risk") or 0)
    confidence = float(out.get("location_confidence") or 0)
    tags = out.get("tags") or []
    print(
        f"[ok] evaluate copresence_risk={copresence:.4f} "
        f"impossible_travel_risk={travel:.4f} location_confidence={confidence:.4f}"
    )
    if tags:
        print(f"[ok] tags={tags}")

    if copresence <= 0:
        print(
            "[fail] expected copresence_risk > 0 when distinct_session_id_24h=4",
            file=sys.stderr,
        )
        return 1

    print(
        "[ok] co-presence feature ready for rules "
        "(see rules/location_copresence_v1.json — shadow mode)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
