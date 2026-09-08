#!/usr/bin/env python3
"""Optional SDK path: same three shipped-pack evaluate POSTs via DecisionClient.

Uses ``fraud_stack_sdk.DecisionClient`` against the same lite evaluate URL as
``walk_receipts.py``. Prints whatever the engine returns. Not a second Day-1
promise and not a hop SKU.

Usage (repo root, desk already up, httpx installed)::

    make sdk-walk
    PYTHONPATH=packages/fraud-sdk-python/src:scripts/oss python3 scripts/oss/sdk_walk.py

Env: DECISION_API (default http://127.0.0.1:8000/decisions), API_KEY / x-api-key.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from first_decision_smoke import _request
from walk_receipts import (
    WALK_CASES,
    RequestFn,
    desk_urls,
    first_click_url,
    format_receipt,
    looking_at_lines,
    summarize_outcomes,
)


class WalkClient(Protocol):
    def evaluate(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        role: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def get_audit(self, trace_id: Any, tenant_id: str) -> dict[str, Any]: ...


def honesty_lines() -> list[str]:
    return looking_at_lines() + [
        "Tarka is Elastic License 2.0 (not open-source). This SDK walk is not a second Day-1 promise.",
    ]


def build_client(base: str, api_key: str | None) -> Any:
    src = Path(__file__).resolve().parents[2] / "packages" / "fraud-sdk-python" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from fraud_stack_sdk import DecisionClient

    return DecisionClient(base, api_key=api_key or "", timeout=30.0)


def _print_next_steps(entity_id: str) -> None:
    urls = desk_urls()
    click = first_click_url(entity_id)
    print()
    print(f"NEXT: {click}")
    print(f"  entity_id={entity_id or 'clone-demo-bot-vpn'}")
    print(f"  receipts  {urls['receipts']}")
    print(f"  Observe   {urls['observe']}")
    print()
    print("What you're looking at:")
    for line in honesty_lines():
        print(f"  - {line}")


def run_walk(
    *,
    request: RequestFn,
    client: WalkClient,
    base: str,
    api_key: str | None,
) -> int:
    st, health = request("GET", f"{base}/v1/health", api_key=api_key, timeout=15.0)
    if st != 200:
        print(f"[fail] health GET {base}/v1/health -> {st} {health!r}", file=sys.stderr)
        print(
            "Hint: start the desk with `make demo` or `bash scripts/oss/up_desk.sh`.",
            file=sys.stderr,
        )
        return 1
    print("[ok] decision-api health")

    decisions: list[str] = []
    for case in WALK_CASES:
        label = str(case["label"])
        body = case["body"]
        entity_id = str(body["entity_id"])
        try:
            out = client.evaluate(
                tenant_id=str(body["tenant_id"]),
                event_type=str(body["event_type"]),
                entity_id=entity_id,
                payload=body.get("payload") if isinstance(body.get("payload"), dict) else None,
                device_context=(
                    body.get("device_context")
                    if isinstance(body.get("device_context"), dict)
                    else None
                ),
                role=str(body["role"]) if body.get("role") is not None else None,
            )
        except Exception as exc:
            print(f"[fail] evaluate {label} via DecisionClient: {exc}", file=sys.stderr)
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                print(
                    "Hint: set ALLOW_INSECURE_NO_AUTH=true in infra/deploy/.env (or pass API_KEY).",
                    file=sys.stderr,
                )
            return 1
        if not isinstance(out, dict):
            print(f"[fail] evaluate {label} non-object response: {out!r}", file=sys.stderr)
            return 1
        trace = out.get("trace_id")
        decision = out.get("decision")
        if not trace:
            print(f"[fail] evaluate {label} missing trace_id: {out!r}", file=sys.stderr)
            return 1
        decision_s = "" if decision is None else str(decision)
        decisions.append(decision_s)
        reasons = out.get("reasons") if isinstance(out.get("reasons"), list) else []
        hits = out.get("rule_hits") if isinstance(out.get("rule_hits"), list) else []
        print(
            format_receipt(
                label=label,
                entity_id=entity_id,
                decision=decision,
                score=out.get("score"),
                trace_id=trace,
                reasons=reasons,
                rule_hits=hits,
            )
        )
        print(f"  Hunt person: /graph lookup entity_id={entity_id}")
        print(f"  pack note: {case.get('note', '')}")

        tenant = str(body.get("tenant_id") or "demo")
        try:
            audit = client.get_audit(trace, tenant)
        except Exception as exc:
            print(f"  [warn] audit GET skipped/unavailable status={exc}")
        else:
            if isinstance(audit, dict):
                print(f"  [ok] audit fetch keys={sorted(audit.keys())[:8]}")
            else:
                print(f"  [warn] audit GET skipped/unavailable status={audit!r}")

    print(summarize_outcomes(decisions))
    last_entity = str(WALK_CASES[-1]["body"]["entity_id"])
    _print_next_steps(last_entity)
    print("SDK receipt walk: PASS")
    return 0


def main() -> int:
    base = os.environ.get("DECISION_API", "http://127.0.0.1:8000/decisions").rstrip("/")
    key = (os.environ.get("API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip() or None
    try:
        client = build_client(base, key)
    except ImportError as exc:
        print(
            "[fail] DecisionClient import failed "
            f"({exc}). Install the Python SDK deps: "
            "pip install -e packages/fraud-sdk-python",
            file=sys.stderr,
        )
        return 1
    return run_walk(request=_request, client=client, base=base, api_key=key)


if __name__ == "__main__":
    raise SystemExit(main())
