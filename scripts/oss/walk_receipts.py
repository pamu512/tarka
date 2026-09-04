#!/usr/bin/env python3
"""Honest clone-and-run walk: a few evaluate POSTs against shipped packs.

Does not invent ALLOW / REVIEW / DENY. Prints whatever evaluate returns,
receipt why, and the Hunt person (`entity_id`). Used by ``make demo`` /
``scripts/oss/up_desk.sh``.

Usage (repo root, stack already up)::

  python3 scripts/oss/walk_receipts.py

Env: DECISION_API (default http://127.0.0.1:8000/decisions), API_KEY / x-api-key.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

from first_decision_smoke import _request

RequestFn = Callable[..., tuple[int, Any]]

# Payloads exercise shipped packs under services/decision-api/rules/:
# default.json, device_signals.json, vertical_payment_risk_v1.json.
# No expected_decision — the engine answers.
WALK_CASES: list[dict[str, Any]] = [
    {
        "label": "clean_payment",
        "note": "No device-risk signals; default.json high_amount_payment is amount>=10000",
        "body": {
            "tenant_id": "demo",
            "entity_id": "clone-demo-clean",
            "event_type": "payment",
            "role": "member",
            "payload": {
                "amount": 25.0,
                "currency": "USD",
                "channel": "card_not_present",
            },
        },
    },
    {
        "label": "bot_signal",
        "note": "device_signals.json sdk_bot + vertical_payment_risk_v1 pay_bot_or_automation",
        "body": {
            "tenant_id": "demo",
            "entity_id": "clone-demo-bot",
            "event_type": "payment",
            "role": "member",
            "payload": {
                "amount": 80.0,
                "currency": "USD",
                "channel": "card_not_present",
            },
            "device_context": {
                "device_id": "clone-demo-bot-device",
                "platform": "web",
                "signals": {"is_bot": True},
            },
        },
    },
    {
        "label": "bot_and_vpn",
        "note": "sdk_bot + sdk_vpn + pay_bot_or_automation on the same shipped packs",
        "body": {
            "tenant_id": "demo",
            "entity_id": "clone-demo-bot-vpn",
            "event_type": "payment",
            "role": "member",
            "payload": {
                "amount": 80.0,
                "currency": "USD",
                "channel": "card_not_present",
            },
            "device_context": {
                "device_id": "clone-demo-bot-vpn-device",
                "platform": "web",
                "signals": {"is_bot": True, "is_vpn": True},
            },
        },
    },
]


def looking_at_lines() -> list[str]:
    return [
        "Packs control the decision. These POSTs hit shipped JSON packs under "
        "services/decision-api/rules/; evaluate never invents ALLOW / REVIEW / DENY.",
        "Receipt why is rule_hits + reasons on the evaluate response and on desk /decisions.",
        "Observe on /ops/shadow is pack canary + leftover promote + live-rule slip — "
        "not live production traffic and not a model.",
        "Empty GRAPH_SERVICE_URL turns hops off (evaluate-only fallback). "
        "Lite compose sets the AGE graph URL.",
        "An edge is real only when the receipt wrote it. This walk does not mock a hop SKU.",
    ]


def desk_urls() -> dict[str, str]:
    return {
        "desk": "http://127.0.0.1:3000",
        "hunt": "http://127.0.0.1:3000/graph",
        "receipts": "http://127.0.0.1:3000/decisions",
        "observe": "http://127.0.0.1:3000/ops/shadow",
    }


def format_receipt(
    *,
    label: str,
    entity_id: str,
    decision: Any,
    score: Any,
    trace_id: Any,
    reasons: list[Any],
    rule_hits: list[Any],
) -> str:
    hits = ",".join(str(h) for h in rule_hits) if rule_hits else "(none)"
    why = "; ".join(str(r) for r in reasons) if reasons else "(none)"
    return (
        f"[receipt] {label} entity_id={entity_id} decision={decision} "
        f"score={score} trace_id={trace_id} rule_hits={hits} reasons={why}"
    )


def summarize_outcomes(decisions: list[str]) -> str:
    normalized = [str(d).strip().lower() for d in decisions if str(d).strip()]
    unique = list(dict.fromkeys(normalized))
    if not unique:
        return "Evaluate returned no decisions."
    if len(unique) == 1:
        return (
            f"All {len(normalized)} receipts came back {unique[0].upper()} "
            "from the shipped packs on this desk — a single outcome is honest, "
            "not a bug. Receipt why and the Hunt person (entity_id) still stand."
        )
    listed = ", ".join(u.upper() for u in unique)
    return f"Evaluate returned {listed} (pack-controlled; not scripted)."


def _print_next_steps() -> None:
    urls = desk_urls()
    print()
    print("Next steps:")
    print(f"  desk      {urls['desk']}")
    print(f"  Hunt      {urls['hunt']}   (home when graph is on)")
    print(f"  receipts  {urls['receipts']}")
    print(f"  Observe   {urls['observe']}")
    print()
    print("What you're looking at:")
    for line in looking_at_lines():
        print(f"  - {line}")


def run_walk(
    *,
    request: RequestFn,
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
        st, out = request(
            "POST",
            f"{base}/v1/decisions/evaluate",
            payload=body,
            api_key=api_key,
        )
        if st != 200 or not isinstance(out, dict):
            print(f"[fail] evaluate {label} status={st} body={out!r}", file=sys.stderr)
            if st in (401, 403):
                print(
                    "Hint: set ALLOW_INSECURE_NO_AUTH=true in infra/deploy/.env "
                    "(or pass API_KEY).",
                    file=sys.stderr,
                )
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

        st_a, audit = request("GET", f"{base}/v1/audit/{trace}", api_key=api_key, timeout=15.0)
        if st_a == 200 and isinstance(audit, dict):
            print(f"  [ok] audit fetch keys={sorted(audit.keys())[:8]}")
        else:
            print(f"  [warn] audit GET skipped/unavailable status={st_a}")

    print(summarize_outcomes(decisions))
    _print_next_steps()
    print("Clone-and-run receipt walk: PASS")
    return 0


def main() -> int:
    base = os.environ.get("DECISION_API", "http://127.0.0.1:8000/decisions").rstrip("/")
    key = (os.environ.get("API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip() or None
    return run_walk(request=_request, base=base, api_key=key)


if __name__ == "__main__":
    raise SystemExit(main())
