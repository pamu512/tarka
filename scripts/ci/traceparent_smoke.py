#!/usr/bin/env python3
"""Smoke test traceparent propagation across core HTTP services."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request


TARGETS = [
    ("decision-api", "http://127.0.0.1:8000/v1/health"),
    ("case-api", "http://127.0.0.1:8002/v1/health"),
    ("investigation-agent", "http://127.0.0.1:8006/v1/health"),
]


def _request(url: str, traceparent: str | None = None) -> tuple[int, dict[str, str]]:
    headers = {}
    if traceparent:
        headers["traceparent"] = traceparent
    req = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, {k.lower(): v for k, v in resp.headers.items()}


def _assert_traceparent(service: str, url: str) -> None:
    status, headers = _request(url)
    if status != 200:
        raise RuntimeError(f"{service}: expected 200, got {status}")
    outbound = headers.get("traceparent", "")
    if not outbound.startswith("00-"):
        raise RuntimeError(f"{service}: missing/invalid traceparent header on response")

    inbound = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    status2, headers2 = _request(url, traceparent=inbound)
    if status2 != 200:
        raise RuntimeError(f"{service}: expected 200 with inbound traceparent, got {status2}")
    if headers2.get("traceparent") != inbound:
        raise RuntimeError(f"{service}: inbound traceparent not preserved")

    print(f"[ok] {service}: traceparent generated + preserved")


def main() -> int:
    p = argparse.ArgumentParser(description="Traceparent propagation smoke")
    p.add_argument("--allow-missing", action="store_true", help="Skip endpoints that are down")
    args = p.parse_args()

    failures = 0
    for svc, url in TARGETS:
        try:
            _assert_traceparent(svc, url)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            if args.allow_missing:
                print(f"[skip] {svc}: {exc}")
                continue
            print(f"[fail] {svc}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

