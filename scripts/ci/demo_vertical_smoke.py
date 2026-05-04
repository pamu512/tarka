#!/usr/bin/env python3
"""End-to-end smoke: Decision evaluate → Case create → Event ingest (+ optional frontend GET).

Prerequisites: Tarka Lite with **ingest** profile, e.g. from repo root::

  docker compose -f deploy/docker-compose.lite.yml --profile ingest up -d --build

Default URLs match published ports (core-api decision mount :8000/decisions, cases :8000/cases, ingest 8007, UI 3000).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ci_dir = Path(__file__).resolve().parent
if str(_ci_dir) not in sys.path:
    sys.path.insert(0, str(_ci_dir))

from demo_vertical_contracts import (
    check_create_case_response,
    check_evaluate_response,
    check_event_ingest_accepted,
    check_frontend_reachable,
)


def _post_json(url: str, payload: dict[str, Any], *, api_key: str | None = None, timeout: float = 30.0) -> tuple[int, dict[str, Any] | str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return resp.status, {}
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, raw


def _get_status(url: str, *, api_key: str | None = None, timeout: float = 15.0) -> int:
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    p = argparse.ArgumentParser(description="Demo vertical: evaluate, case, ingest, optional UI.")
    p.add_argument(
        "--decision-api",
        default=os.environ.get("DEMO_DECISION_API", "http://127.0.0.1:8000/decisions"),
    )
    p.add_argument("--case-api", default=os.environ.get("DEMO_CASE_API", "http://127.0.0.1:8000/cases"))
    p.add_argument("--event-ingest", default=os.environ.get("DEMO_EVENT_INGEST", "http://127.0.0.1:8007"))
    p.add_argument("--frontend", default=os.environ.get("DEMO_FRONTEND", "http://127.0.0.1:3000"))
    p.add_argument(
        "--api-key",
        default=(os.environ.get("DEMO_API_KEY") or "").strip() or None,
        help="x-api-key when services use non-empty API_KEYS (see deploy/docker-compose.demo-vertical.yml).",
    )
    p.add_argument("--skip-frontend", action="store_true")
    args = p.parse_args()
    d_base = args.decision_api.rstrip("/")
    c_base = args.case_api.rstrip("/")
    e_base = args.event_ingest.rstrip("/")
    key = (args.api_key or "").strip() or None

    # 1) Ready gates
    for name, u in (
        ("decision", f"{d_base}/v1/ready"),
        ("case", f"{c_base}/v1/health"),
        ("ingest", f"{e_base}/v1/ready"),
    ):
        st = _get_status(u, api_key=key)
        if st != 200:
            print(f"[fail] {name} GET {u} -> {st}", file=sys.stderr)
            return 1

    # 2) Evaluate
    ev_body = {
        "tenant_id": "demo-vertical",
        "entity_id": "ent-demo-1",
        "event_type": "login",
        "payload": {"amount": 0, "currency": "USD"},
    }
    st, out = _post_json(f"{d_base}/v1/decisions/evaluate", ev_body, api_key=key)
    if st != 200 or not isinstance(out, dict):
        print(f"[fail] evaluate: status={st} body={out!r}", file=sys.stderr)
        return 1
    try:
        check_evaluate_response(out)
    except AssertionError as e:
        print(f"[fail] evaluate shape: {e}", file=sys.stderr)
        return 1
    trace_id = str(out["trace_id"])
    print(f"[ok] evaluate decision={out.get('decision')} trace_id={trace_id}")

    # 3) Case from evaluate trace
    case_body = {
        "tenant_id": "demo-vertical",
        "title": "Demo vertical",
        "entity_id": "ent-demo-1",
        "trace_id": trace_id,
        "priority": "low",
    }
    st, c_out = _post_json(f"{c_base}/v1/cases", case_body, api_key=key)
    if st in (401, 403):
        # Insecure dev user is often viewer; case create needs analyst. Fall back to list.
        u = f"{c_base}/v1/cases?tenant_id=demo-vertical&limit=1"
        st_l = _get_status(u, api_key=key)
        if st_l != 200:
            print(
                f"[fail] case create 403 and case list {st_l}; use API_KEYS + x-api-key "
                f"(see deploy/docker-compose.demo-vertical.yml) for full vertical.",
                file=sys.stderr,
            )
            return 1
        print("[ok] case API reachable (list-only; use demo-vertical compose + API key for create)")
    elif st != 201 or not isinstance(c_out, dict):
        print(f"[fail] case create: status={st} body={c_out!r}", file=sys.stderr)
        return 1
    else:
        try:
            check_create_case_response(c_out)
        except AssertionError as e:
            print(f"[fail] case shape: {e}", file=sys.stderr)
            return 1
        print(f"[ok] case created id={c_out.get('id')}")

    # 4) Ingest (flat event; same tenant/entity for narrative consistency)
    ing_body = {
        "tenant_id": "demo-vertical",
        "entity_id": "ent-demo-1",
        "event_type": "login",
        "payload": {"source": "demo_vertical_smoke"},
    }
    st, _ing = _post_json(f"{e_base}/v1/events", ing_body, api_key=key)
    try:
        check_event_ingest_accepted(st)
    except AssertionError:
        print(f"[fail] ingest: status={st} body={_ing!r}", file=sys.stderr)
        return 1
    print("[ok] event accepted by ingest")

    if not args.skip_frontend:
        f_st = _get_status(args.frontend)
        try:
            check_frontend_reachable(f_st)
        except AssertionError:
            print(f"[warn] frontend GET {args.frontend} -> {f_st} (use --skip-frontend to ignore)", file=sys.stderr)
        else:
            print(f"[ok] frontend reachable (status {f_st})")

    print("demo vertical smoke: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
