#!/usr/bin/env python3
"""Prove sync enforcement_action + optional enforcement webhook delivery.

Usage (repo root)::

  # Terminal A
  python3 scripts/oss/enforcement_webhook_mock.py --port 8765

  # Terminal B (Lite up, or point DECISION_API)
  export TARKA_ENFORCEMENT_WEBHOOK_URL=http://127.0.0.1:8765/enforcement
  # If decision-api already running, set webhook URL in its env and restart.
  # This script always asserts the *sync* field; webhook check is opt-in.

  python3 scripts/oss/decide_to_act_smoke.py

Env: DECISION_API (default http://127.0.0.1:8000/decisions), API_KEY / DEMO_API_KEY,
     EXPECT_WEBHOOK=1 to also POST via apply path is N/A here — sync-only smoke.
See docs/docs/guides/decide-to-act-enforcement.md
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
        print(f"[fail] health -> {st} {health!r}", file=sys.stderr)
        return 1
    print("[ok] decision-api health")

    # Blacklist-style entity is not guaranteed; assert field presence + mapping via
    # normal evaluate. Deny is environment-dependent — require key exists and is one of verbs.
    body = {
        "tenant_id": "demo",
        "entity_id": "decide-to-act-smoke",
        "event_type": "payment",
        "payload": {"amount": 42.0, "currency": "USD", "channel": "card_not_present"},
    }
    st, out = _request(
        "POST",
        f"{base}/v1/decisions/evaluate",
        payload=body,
        api_key=key,
    )
    if st != 200 or not isinstance(out, dict):
        print(f"[fail] evaluate status={st} body={out!r}", file=sys.stderr)
        return 1

    decision = out.get("decision")
    rec = out.get("recommended_action")
    enf = out.get("enforcement_action")
    print(f"[ok] decision={decision!r} recommended_action={rec!r} enforcement_action={enf!r}")

    if enf not in ("allow", "step_up", "block"):
        print(
            f"[fail] expected enforcement_action in allow|step_up|block, got {enf!r}",
            file=sys.stderr,
        )
        return 1

    # Local mapping check (same rules as decision-api.enforcement).
    if decision == "deny" and enf != "block":
        print("[fail] deny must map to block", file=sys.stderr)
        return 1
    if decision != "deny" and isinstance(rec, str) and (
        rec.lower().replace("-", "_").startswith("step_up")
        or rec.lower().startswith("challenge")
    ):
        if enf != "step_up":
            print("[fail] step-up recommended_action must map to step_up", file=sys.stderr)
            return 1

    print("[ok] sync enforcement_action present and consistent")
    print(
        "Hint: set TARKA_ENFORCEMENT_WEBHOOK_URL on decision-api to "
        "http://127.0.0.1:8765/enforcement and run enforcement_webhook_mock.py "
        "to see async tarka.enforcement/v1 delivery."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
