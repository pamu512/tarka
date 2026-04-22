#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import string
import time
from collections import Counter
from typing import Any

import httpx

"""Minimal adversarial fuzz harness for POST /v1/decisions/evaluate."""


def _rand_id(prefix: str) -> str:
    return f"{prefix}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"


def _base_payload() -> dict[str, Any]:
    return {
        "tenant_id": "demo",
        "event_type": "payment",
        "entity_id": _rand_id("acct"),
        "payload": {"amount": random.randint(1, 500), "currency": "USD"},
        "device_context": {
            "device_id": _rand_id("dev"),
            "platform": "web",
            "signals": {"is_vpn": random.choice([True, False]), "automation_detected": random.choice([True, False])},
        },
        "metadata": {},
    }


def _mutations() -> list[tuple[str, Any]]:
    return [
        ("remove_tenant_id", lambda p: p.pop("tenant_id", None)),
        ("invalid_event_type", lambda p: p.__setitem__("event_type", "unknown_event")),
        ("bad_amount_type", lambda p: p["payload"].__setitem__("amount", "not-a-number")),
        ("huge_entity_id", lambda p: p.__setitem__("entity_id", "x" * 2048)),
        ("null_payload", lambda p: p.__setitem__("payload", None)),
        ("nested_noise", lambda p: p["payload"].__setitem__("nested", {"noise": ["x" * 256] * 20})),
        ("negative_amount", lambda p: p["payload"].__setitem__("amount", -99999)),
        ("bad_geo_values", lambda p: p["device_context"]["signals"].update({"geo_lat": "nan", "geo_lon": "oops"})),
        ("oversized_metadata", lambda p: p.__setitem__("metadata", {"blob": "x" * 20_000})),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuzz Decision API evaluate contract")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Decision API base URL")
    parser.add_argument("--api-key", default="", help="x-api-key header")
    parser.add_argument("--rounds", type=int, default=50, help="Number of fuzz requests")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    mutators = _mutations()
    counters = Counter()
    start = time.perf_counter()
    with httpx.Client(timeout=args.timeout) as client:
        for _ in range(max(1, args.rounds)):
            payload = _base_payload()
            name, mutate = random.choice(mutators)
            mutate(payload)
            headers = {"content-type": "application/json"}
            if args.api_key:
                headers["x-api-key"] = args.api_key
            try:
                resp = client.post(f"{args.base_url.rstrip('/')}/v1/decisions/evaluate", headers=headers, content=json.dumps(payload))
                counters[f"status_{resp.status_code}"] += 1
            except Exception:
                counters["request_exception"] += 1
            counters[f"mutation_{name}"] += 1

    elapsed = (time.perf_counter() - start) * 1000.0
    print(json.dumps({"rounds": args.rounds, "elapsed_ms": round(elapsed, 2), "results": dict(counters)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
