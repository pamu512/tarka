#!/usr/bin/env python3
"""Investigation smoke: decision evaluate -> case -> decision-explanation schema check."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _json_request(url: str, *, method: str = "GET", body: dict | None = None, api_key: str = "") -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} failed ({e.code}): {detail[:800]}") from None


def main() -> int:
    p = argparse.ArgumentParser(description="Smoke check for investigation decision explanation chain.")
    p.add_argument("--tenant-id", default=os.environ.get("SMOKE_TENANT_ID", "demo"))
    p.add_argument("--decision-api-url", default=os.environ.get("SMOKE_DECISION_API_URL", "http://localhost:8000"))
    p.add_argument("--case-api-url", default=os.environ.get("SMOKE_CASE_API_URL", "http://localhost:8002"))
    p.add_argument("--api-key", default=os.environ.get("SMOKE_API_KEY", ""))
    args = p.parse_args()

    tenant = args.tenant_id
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entity_id = f"smoke-{tenant}-entity"

    eval_payload = {
        "event_type": "payment_auth",
        "entity_id": entity_id,
        "tenant_id": tenant,
        "payload": {"amount": 199.95, "currency": "USD", "timestamp": now},
        "metadata": {"source": "investigation_e2e_smoke"},
    }
    decision = _json_request(
        f"{args.decision_api_url.rstrip('/')}/v1/decisions/evaluate",
        method="POST",
        body=eval_payload,
        api_key=args.api_key,
    )
    trace_id = str(decision.get("trace_id") or "").strip()
    if not trace_id:
        raise SystemExit("Decision evaluate did not return trace_id")

    case_payload = {
        "tenant_id": tenant,
        "title": "Investigation smoke case",
        "entity_id": entity_id,
        "trace_id": trace_id,
        "priority": "medium",
    }
    case = _json_request(
        f"{args.case_api_url.rstrip('/')}/v1/cases",
        method="POST",
        body=case_payload,
        api_key=args.api_key,
    )
    case_id = str(case.get("id") or "").strip()
    if not case_id:
        raise SystemExit("Case create did not return id")

    q = urllib.parse.urlencode({"tenant_id": tenant})
    explanation = _json_request(
        f"{args.case_api_url.rstrip('/')}/v1/cases/{urllib.parse.quote(case_id)}/decision-explanation?{q}",
        api_key=args.api_key,
    )
    graph_expl = explanation.get("graph_decision_explanation")
    schema_id = graph_expl.get("schema_id") if isinstance(graph_expl, dict) else None
    if schema_id != "tarka.graph_decision_explanation/v1":
        source = explanation.get("source")
        raise SystemExit(
            "Decision explanation schema assertion failed: "
            f"expected tarka.graph_decision_explanation/v1, got {schema_id!r} (source={source!r})"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "tenant_id": tenant,
                "trace_id": trace_id,
                "case_id": case_id,
                "decision": decision.get("decision"),
                "score": decision.get("score"),
                "schema_id": schema_id,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
