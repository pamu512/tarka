#!/usr/bin/env python3
"""Smoke-check core operational endpoints for decision/agent/ingest services."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _get_json(
    url: str, *, api_key: str | None = None, timeout: float = 10.0
) -> tuple[int, dict[str, Any]]:
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload: dict[str, Any] = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"detail": body[:500]}
        return exc.code, payload


def _assert(cond: bool, message: str) -> None:
    if not cond:
        raise RuntimeError(message)


def _check_decision_api(base: str) -> None:
    url = f"{base.rstrip('/')}/v1/ready"
    status, payload = _get_json(url)
    _assert(status == 200, f"decision-api /v1/ready expected 200, got {status}: {payload}")
    _assert(payload.get("ready") is True, f"decision-api /v1/ready expected ready=true: {payload}")
    checks = payload.get("checks")
    _assert(isinstance(checks, dict), f"decision-api /v1/ready checks must be object: {payload}")
    for key in ("redis", "http_client", "database"):
        _assert(key in checks, f"decision-api /v1/ready missing checks.{key}: {payload}")
    print("[ok] decision-api ready")


def _check_investigation_agent(base: str, api_key: str) -> None:
    ready_url = f"{base.rstrip('/')}/v1/ready"
    status, payload = _get_json(ready_url, api_key=api_key)
    _assert(status == 200, f"investigation-agent /v1/ready expected 200, got {status}: {payload}")
    _assert(
        payload.get("status") == "ready",
        f"investigation-agent /v1/ready expected status=ready: {payload}",
    )

    health_url = f"{base.rstrip('/')}/v1/ops/llm-health"
    status, payload = _get_json(health_url, api_key=api_key)
    _assert(
        status == 200,
        f"investigation-agent /v1/ops/llm-health expected 200, got {status}: {payload}",
    )
    _assert(
        "providers" in payload,
        f"investigation-agent /v1/ops/llm-health missing providers: {payload}",
    )

    cost_url = f"{base.rstrip('/')}/v1/ops/llm-costs?hours=24"
    status, payload = _get_json(cost_url, api_key=api_key)
    _assert(
        status == 200,
        f"investigation-agent /v1/ops/llm-costs expected 200, got {status}: {payload}",
    )
    _assert(
        "total_calls" in payload and "by_provider" in payload,
        f"investigation-agent /v1/ops/llm-costs shape invalid: {payload}",
    )
    print("[ok] investigation-agent ready + llm ops")


def _check_event_ingest(base: str, api_key: str) -> None:
    ready_url = f"{base.rstrip('/')}/v1/ready"
    status, payload = _get_json(ready_url)
    _assert(status == 200, f"event-ingest /v1/ready expected 200, got {status}: {payload}")
    _assert(payload.get("ready") is True, f"event-ingest /v1/ready expected ready=true: {payload}")
    checks = payload.get("checks")
    _assert(isinstance(checks, dict), f"event-ingest /v1/ready checks must be object: {payload}")
    for key in ("nats_connected", "http_client", "redis_ok"):
        _assert(key in checks, f"event-ingest /v1/ready missing checks.{key}: {payload}")

    schema_url = f"{base.rstrip('/')}/v1/schema-registry/status"
    status, payload = _get_json(schema_url, api_key=api_key)
    _assert(
        status == 200,
        f"event-ingest /v1/schema-registry/status expected 200, got {status}: {payload}",
    )
    _assert(
        payload.get("schema_id") == "fraud-event", f"event-ingest schema_id mismatch: {payload}"
    )
    versions = payload.get("versions")
    _assert(
        isinstance(versions, list) and len(versions) >= 1,
        f"event-ingest schema versions invalid: {payload}",
    )
    print("[ok] event-ingest ready + schema registry")


def main() -> int:
    parser = argparse.ArgumentParser(description="Operational endpoint smoke checks")
    parser.add_argument("--decision-api", default="http://127.0.0.1:8000")
    parser.add_argument("--investigation-agent", default="http://127.0.0.1:8006")
    parser.add_argument("--event-ingest", default="http://127.0.0.1:8007")
    parser.add_argument("--api-key", default="tarka-local")
    args = parser.parse_args()

    _check_decision_api(args.decision_api)
    _check_investigation_agent(args.investigation_agent, args.api_key)
    _check_event_ingest(args.event_ingest, args.api_key)
    print("operational surface smoke passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"operational surface smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
