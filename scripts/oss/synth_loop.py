#!/usr/bin/env python3
"""Local operator loop: keep POSTing evaluate (and occasional late-labels).

Keeps a running local desk live for an evaluate-loop demo. Does not start
compose. Does not invent ALLOW / REVIEW / DENY. Local operator tool only.

Usage (repo root, stack already up)::

  python3 scripts/oss/synth_loop.py
  python3 scripts/oss/synth_loop.py --interval 2 --max 30 --label-every 10
  python3 scripts/oss/synth_loop.py --dry-run --max 3

Env: DECISION_API (default http://127.0.0.1:8000/decisions), API_KEY / x-api-key.
Optional REQUEST_SIGNATURE_SECRET to HMAC late-label when the desk requires it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any, Callable

from first_decision_smoke import _request
from walk_receipts import WALK_CASES, format_receipt

RequestFn = Callable[..., tuple[int, Any]]
SleepFn = Callable[[float], None]

# Mirror walk cases, then add shipped-pack field variants. No expected_decision.
SYNTH_CASES: list[dict[str, Any]] = [
    copy.deepcopy(case) for case in WALK_CASES
] + [
    {
        "label": "high_amount",
        "note": "default.json high_amount_payment is amount>=10000",
        "body": {
            "tenant_id": "demo",
            "entity_id": "synth-high-amount",
            "event_type": "payment",
            "role": "member",
            "payload": {
                "amount": 10000.0,
                "currency": "USD",
                "channel": "card_not_present",
            },
        },
    },
    {
        "label": "emulator",
        "note": "device_signals.json sdk_emulator; vertical pay_high_amount_emulator at amount>=5000",
        "body": {
            "tenant_id": "demo",
            "entity_id": "synth-emulator",
            "event_type": "payment",
            "role": "member",
            "payload": {
                "amount": 5000.0,
                "currency": "USD",
                "channel": "card_not_present",
            },
            "device_context": {
                "device_id": "synth-emulator-device",
                "platform": "web",
                "signals": {"is_emulator": True},
            },
        },
    },
    {
        "label": "login_event",
        "note": "login event_type; device_signals still apply when signals are set",
        "body": {
            "tenant_id": "demo",
            "entity_id": "synth-login",
            "event_type": "login",
            "role": "member",
            "payload": {
                "amount": 0.0,
                "currency": "USD",
                "channel": "web",
            },
            "device_context": {
                "device_id": "synth-login-device",
                "platform": "web",
                "signals": {"is_vpn": True},
            },
        },
    },
]

EVENT_TYPES = ("payment", "login")
AMOUNTS = (25.0, 80.0, 150.0, 10000.0)
LABEL_KINDS = ("fp", "fraud")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local operator tool: loop evaluate POSTs (and occasional late-labels) "
            "against a running desk. Does not start compose."
        )
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between evaluate POSTs (default 2).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="Evaluate attempts then exit. 0 = forever (default).",
    )
    parser.add_argument(
        "--label-every",
        type=int,
        default=10,
        help="POST late-label after every N successful evaluates (default 10). 0 = never.",
    )
    parser.add_argument(
        "--tenant",
        default="demo",
        help="tenant_id on evaluate and late-label (default demo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads only; do not POST.",
    )
    return parser


def build_evaluate_body(tick: int, *, tenant: str) -> dict[str, Any]:
    if tick < 0:
        raise ValueError("tick must be >= 0")
    case = SYNTH_CASES[tick % len(SYNTH_CASES)]
    body = copy.deepcopy(case["body"])
    if not isinstance(body, dict):
        raise TypeError("synth case body must be a dict")
    body["tenant_id"] = tenant
    base_entity = str(body.get("entity_id") or "synth")
    body["entity_id"] = f"{base_entity}-{tick}"
    body["event_type"] = EVENT_TYPES[tick % len(EVENT_TYPES)]
    payload = body.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    payload = dict(payload)
    payload["amount"] = AMOUNTS[tick % len(AMOUNTS)]
    body["payload"] = payload
    dc = body.get("device_context")
    if not isinstance(dc, dict):
        dc = {}
    dc = dict(dc)
    signals = dc.get("signals")
    if isinstance(signals, dict):
        dc["signals"] = dict(signals)
    base_dev = str(dc.get("device_id") or f"{base_entity}-device")
    dc["device_id"] = f"{base_dev}-{tick}"
    dc.setdefault("platform", "web")
    body["device_context"] = dc
    return body


def build_label_payload(
    eval_out: dict[str, Any],
    *,
    tenant: str,
    label_kind: str,
) -> dict[str, Any]:
    kind = str(label_kind or "").strip() or "fp"
    out: dict[str, Any] = {"tenant_id": tenant, "label_kind": kind}
    token = str(eval_out.get("evaluation_token") or "").strip()
    if token:
        out["evaluation_token"] = token
        return out
    trace = str(eval_out.get("trace_id") or "").strip()
    if trace:
        out["trace_id"] = trace
    return out


def _signature_headers(raw: bytes, secret: str) -> dict[str, str]:
    # ponytail: stdlib HMAC, same message as tarka_request_signature (upgrade: import it).
    ts = str(int(time.time()))
    msg = ts.encode("utf-8") + b"\n" + raw
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return {"X-Tarka-Timestamp": ts, "X-Tarka-Signature": sig}


def _label_extra_headers(payload: dict[str, Any]) -> dict[str, str] | None:
    secret = (os.environ.get("REQUEST_SIGNATURE_SECRET") or "").strip()
    if not secret:
        return None
    raw = json.dumps(payload).encode("utf-8")
    return _signature_headers(raw, secret)


def _print_tick(
    *,
    tick: int,
    entity_id: str,
    decision: Any,
    score: Any,
    trace_id: Any,
    reasons: list[Any],
    rule_hits: list[Any],
) -> None:
    line = format_receipt(
        label=f"tick-{tick}",
        entity_id=entity_id,
        decision=decision,
        score=score,
        trace_id=trace_id,
        reasons=reasons,
        rule_hits=rule_hits,
    )
    print(line)


def run_loop(
    *,
    request: RequestFn,
    base: str,
    api_key: str | None,
    interval: float,
    max_events: int,
    label_every: int,
    tenant: str,
    dry_run: bool,
    sleeper: SleepFn = time.sleep,
) -> int:
    try:
        return _run_loop(
            request=request,
            base=base.rstrip("/"),
            api_key=api_key,
            interval=interval,
            max_events=max_events,
            label_every=label_every,
            tenant=tenant,
            dry_run=dry_run,
            sleeper=sleeper,
        )
    except KeyboardInterrupt:
        print("[stop] synth-loop interrupted", file=sys.stderr)
        return 0


def _run_loop(
    *,
    request: RequestFn,
    base: str,
    api_key: str | None,
    interval: float,
    max_events: int,
    label_every: int,
    tenant: str,
    dry_run: bool,
    sleeper: SleepFn,
) -> int:
    if interval < 0:
        print("[fail] --interval must be >= 0", file=sys.stderr)
        return 1
    if max_events < 0:
        print("[fail] --max must be >= 0", file=sys.stderr)
        return 1
    if label_every < 0:
        print("[fail] --label-every must be >= 0", file=sys.stderr)
        return 1

    eval_url = f"{base}/v1/decisions/evaluate"
    label_url = f"{base}/v1/webhooks/late-label"
    tick = 0
    successes = 0

    while max_events == 0 or tick < max_events:
        body = build_evaluate_body(tick=tick, tenant=tenant)
        entity_id = str(body.get("entity_id") or "")

        if dry_run:
            print(f"[dry-run] POST {eval_url}")
            print(json.dumps(body, indent=2))
            successes += 1
            if label_every and successes % label_every == 0:
                preview = build_label_payload(
                    {"evaluation_token": f"dry-run-{entity_id}"},
                    tenant=tenant,
                    label_kind=LABEL_KINDS[(successes - 1) % len(LABEL_KINDS)],
                )
                print(f"[dry-run] POST {label_url}")
                print(json.dumps(preview, indent=2))
        else:
            st, out = request(
                "POST",
                eval_url,
                payload=body,
                api_key=api_key,
            )
            if st != 200 or not isinstance(out, dict):
                print(
                    f"[warn] evaluate tick={tick} entity_id={entity_id} "
                    f"status={st} body={out!r}",
                    file=sys.stderr,
                )
            else:
                successes += 1
                reasons = out.get("reasons") if isinstance(out.get("reasons"), list) else []
                hits = out.get("rule_hits") if isinstance(out.get("rule_hits"), list) else []
                _print_tick(
                    tick=tick,
                    entity_id=entity_id,
                    decision=out.get("decision"),
                    score=out.get("score"),
                    trace_id=out.get("trace_id"),
                    reasons=reasons,
                    rule_hits=hits,
                )
                if label_every and successes % label_every == 0:
                    kind = LABEL_KINDS[(successes - 1) % len(LABEL_KINDS)]
                    label_body = build_label_payload(out, tenant=tenant, label_kind=kind)
                    if not (
                        label_body.get("evaluation_token") or label_body.get("trace_id")
                    ):
                        print(
                            f"[warn] late-label skip tick={tick}: no evaluation_token "
                            "or trace_id on evaluate response",
                            file=sys.stderr,
                        )
                    else:
                        extra = _label_extra_headers(label_body)
                        lst, lout = request(
                            "POST",
                            label_url,
                            payload=label_body,
                            api_key=api_key,
                            extra_headers=extra,
                        )
                        if lst != 200:
                            print(
                                f"[warn] late-label bind failed tick={tick} "
                                f"status={lst} body={lout!r}",
                                file=sys.stderr,
                            )
                        else:
                            print(
                                f"[ok] late-label kind={kind} "
                                f"join={label_body.get('evaluation_token') or label_body.get('trace_id')}"
                            )

        tick += 1
        if max_events == 0 or tick < max_events:
            if interval > 0 and not dry_run:
                sleeper(interval)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return int(code)
    base = os.environ.get("DECISION_API", "http://127.0.0.1:8000/decisions").rstrip("/")
    key = (os.environ.get("API_KEY") or os.environ.get("DEMO_API_KEY") or "").strip() or None
    return run_loop(
        request=_request,
        base=base,
        api_key=key,
        interval=float(args.interval),
        max_events=int(args.max),
        label_every=int(args.label_every),
        tenant=str(args.tenant or "demo"),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
