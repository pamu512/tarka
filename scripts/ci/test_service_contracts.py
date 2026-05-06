#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch_json(url: str, timeout: float = 8.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"detail": body[:400]}
        return exc.code, payload


def assert_health(name: str, url: str) -> None:
    status, payload = fetch_json(url)
    if status != 200 or payload.get("status") != "ok":
        raise RuntimeError(f"{name} contract failed: GET {url} -> {status} {payload}")


def main() -> int:
    p = argparse.ArgumentParser(description="Service contract checks for core dependencies.")
    p.add_argument("--decision-api", default="http://127.0.0.1:8000")
    p.add_argument("--ml-scoring", default="http://127.0.0.1:8005")
    p.add_argument("--graph-service", default="http://127.0.0.1:8001")
    p.add_argument("--data-platform", default="http://127.0.0.1:8014")
    args = p.parse_args()

    assert_health("decision-api", f"{args.decision_api.rstrip('/')}/v1/health")
    assert_health("ml-scoring", f"{args.ml_scoring.rstrip('/')}/v1/health")
    assert_health("graph-service", f"{args.graph_service.rstrip('/')}/v1/health")
    assert_health("data-platform", f"{args.data_platform.rstrip('/')}/v1/health")
    print("service contracts ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"service contract test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
