#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str  # scam | legit
    expected: set[str]
    payload: dict[str, Any]


SCENARIOS: list[Scenario] = [
    Scenario(
        name="scam_phone_reputation",
        label="scam",
        expected={"review", "deny"},
        payload={
            "tenant_id": "proof-sprint",
            "entity_id": "acct_scam_1",
            "event_type": "payment",
            "payload": {
                "amount": 999.0,
                "currency": "USD",
                "phone": "+85215550001",
                "url": "https://suspicious.example/checkout",
                "ip_address": "203.0.113.44",
            },
            "device_context": {"device_id": "dev-scam-1", "platform": "web", "signals": {"is_bot": True}},
        },
    ),
    Scenario(
        name="scam_link_abuse",
        label="scam",
        expected={"review", "deny"},
        payload={
            "tenant_id": "proof-sprint",
            "entity_id": "acct_scam_2",
            "event_type": "payment",
            "payload": {
                "amount": 750.0,
                "currency": "USD",
                "phone": "+85215550002",
                "url": "https://fraud-link.example/pay",
                "ip_address": "198.51.100.77",
            },
            "device_context": {"device_id": "dev-scam-2", "platform": "web", "signals": {"is_bot": True}},
        },
    ),
    Scenario(
        name="legit_repeat_buyer",
        label="legit",
        expected={"allow"},
        payload={
            "tenant_id": "proof-sprint",
            "entity_id": "acct_legit_1",
            "event_type": "payment",
            "payload": {
                "amount": 42.0,
                "currency": "USD",
                "phone": "+85216660001",
                "url": "https://merchant.example/checkout",
                "ip_address": "198.51.100.18",
            },
            "device_context": {"device_id": "dev-legit-1", "platform": "web", "signals": {"is_bot": False}},
        },
    ),
    Scenario(
        name="legit_low_value_login",
        label="legit",
        expected={"allow"},
        payload={
            "tenant_id": "proof-sprint",
            "entity_id": "acct_legit_2",
            "event_type": "login",
            "payload": {
                "amount": 0.0,
                "currency": "USD",
                "phone": "+85216660002",
                "ip_address": "203.0.113.8",
            },
            "device_context": {"device_id": "dev-legit-2", "platform": "web", "signals": {"is_bot": False}},
        },
    ),
]


def _post_json(url: str, payload: dict[str, Any], *, api_key: str | None = None, timeout: float = 8.0) -> tuple[int, dict[str, Any]]:
    headers = {"content-type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:500]}


def run(base_url: str, api_key: str | None) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/v1/decisions/evaluate"
    total = len(SCENARIOS)
    ok = 0
    legit_total = 0
    legit_fp = 0
    scam_total = 0
    scam_hits = 0
    rows: list[dict[str, Any]] = []

    for scenario in SCENARIOS:
        status, out = _post_json(endpoint, scenario.payload, api_key=api_key)
        decision = str(out.get("decision") or "error")
        matched = status == 200 and decision in scenario.expected
        if matched:
            ok += 1
        if scenario.label == "legit":
            legit_total += 1
            if status == 200 and decision != "allow":
                legit_fp += 1
        else:
            scam_total += 1
            if status == 200 and decision in {"review", "deny"}:
                scam_hits += 1
        rows.append(
            {
                "name": scenario.name,
                "label": scenario.label,
                "http_status": status,
                "decision": decision,
                "expected": sorted(scenario.expected),
                "matched": matched,
            }
        )

    precision_proxy = round((scam_hits / max((scam_hits + legit_fp), 1)), 4)
    recall_proxy = round((scam_hits / max(scam_total, 1)), 4)
    false_positive_rate = round((legit_fp / max(legit_total, 1)), 4)
    return {
        "total": total,
        "matched": ok,
        "match_rate": round(ok / max(total, 1), 4),
        "scam_hit_rate": recall_proxy,
        "precision_proxy": precision_proxy,
        "false_positive_rate": false_positive_rate,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay labeled Scameter-oriented scenarios against decision-api.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    result = run(args.base_url, args.api_key)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"scameter scenario replay failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
