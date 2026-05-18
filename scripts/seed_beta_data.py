#!/usr/bin/env python3
"""Seed beta demo data: 50 ``TransactionSchema`` rows via Orchestrator ``POST /v1/ingest``.

Cohort mix (deterministic demo rules in ``rule_engine``)::

  * **5 × deterministic fraud (BLOCK)** — ``metadata`` contains ``STRESS_BLOCK_LANE`` (same contract
    as ``scripts/bench_ingestion.py``). Each row carries a distinct ``fraud_pattern`` label for UI
    / QA narration.
  * **5 × borderline (SHADOW_REVIEW)** — ``amount`` > 100, **no** ``STRESS_BLOCK_LANE``, so the
    high-amount rule fires and the orchestrator calls Shadow when ``SHADOW_AGENT_URL`` is set.
  * **40 × benign** — ``amount`` ≤ 100, no block lane; implicit allow path.

**Environment**

* ``ORCHESTRATOR_URL`` — default ``http://127.0.0.1:8790/v1/ingest``
* ``SHADOW_AGENT_URL`` / ``SHADOW_API_KEY`` — must match orchestrator Shadow config or SHADOW rows
  return **503** (orchestrator requires sidecar when rules emit ``SHADOW_REVIEW``).

**UI / Audit gate (manual)**

1. Bring up Orchestrator + Rule Engine + Shadow (with ``SHADOW_DATABASE_URL`` pointed at a **fresh**
   Postgres or SQLite volume if you need empty ``audit_logs``).
2. Run this script; confirm exit code **0** and open ``artifacts/seed_beta_manifest.json``.
3. Start the **frontend** (Vite ``frontend/``) with env so ``recentAudit`` hits a real API **or**
   keep mock mode and compare counts only.
4. On the dashboard **ticker**, expect **5** rows with BLOCK-style risk, **5** SHADOW/FLAG-style
   rows (depending on Shadow health), and **40** lower-risk rows — **50** ingest events total.
5. In **Audit** / inspector flows, cross-check ``entity_id`` / amounts against the manifest; Shadow
   path rows should gain ``audit_logs`` entries in the sidecar DB when ``/v1/analyze`` succeeds.

Usage::

    export ORCHESTRATOR_URL=http://127.0.0.1:8790/v1/ingest
    export SHADOW_AGENT_URL=http://127.0.0.1:8801
    export SHADOW_API_KEY=your-key
    python3 scripts/seed_beta_data.py
    python3 scripts/seed_beta_data.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class SeedRow:
    """Internal plan row (``kind`` is not sent to the API)."""

    kind: str
    fraud_pattern: str | None
    payload: dict[str, Any]


def _iso(ts: datetime) -> str:
    """RFC3339 offset datetime (matches orchestrator / ingestor tests)."""
    return ts.astimezone(UTC).replace(microsecond=0).isoformat()


def build_seed_rows() -> list[SeedRow]:
    """Exactly 50 rows: 5 BLOCK fraud, 5 SHADOW borderline, 40 allow."""
    base = datetime.now(UTC)
    rows: list[SeedRow] = []

    fraud_specs: list[tuple[str, str, float, dict[str, Any]]] = [
        ("card_testing_ring", "Synthetic rapid-fire low-ticket card testing.", 42.0, {"mcc": "5999"}),
        ("synthetic_identity", "New entity + high-risk email domain velocity.", 88.5, {"channel": "card_not_present"}),
        ("velocity_bust_out", "Short-window spend vs historical baseline.", 120.0, {"velocity_score": 0.94}),
        ("ato_sweeper", "Account takeover with immediate outbound transfers.", 55.0, {"device_new": True}),
        ("mule_fan_in", "Fan-in to single beneficiary across unrelated senders.", 33.33, {"beneficiary_risk": "elevated"}),
    ]
    for i, (pid, narrative, amt, extra) in enumerate(fraud_specs, start=1):
        meta = {
            "seed": "beta",
            "cohort": "deterministic_fraud",
            "fraud_pattern": pid,
            "narrative": narrative,
            "lane": "STRESS_BLOCK_LANE",
            **extra,
        }
        rows.append(
            SeedRow(
                "block",
                pid,
                {
                    "entity_id": str(uuid4()),
                    "amount": amt,
                    "timestamp": _iso(base + timedelta(seconds=i)),
                    "metadata": meta,
                },
            )
        )

    borderline_specs: list[tuple[str, float, dict[str, Any]]] = [
        ("just_over_threshold", 100.01, {"risk_band": "L1"}),
        ("ATO_borderline", 101.0, {"login_anomaly": True}),
        ("wire_urgency", 150.0, {"beneficiary_age_days": 2}),
        ("split_payment_smurf", 199.99, {"split_index": 2, "split_of": 600}),
        ("high_value_card_cnp", 9999.99, {"3ds": "attempted"}),
    ]
    for i, (label, amt, extra) in enumerate(borderline_specs, start=1):
        meta = {
            "seed": "beta",
            "cohort": "borderline_shadow",
            "borderline_case": label,
            **extra,
        }
        rows.append(
            SeedRow(
                "shadow",
                label,
                {
                    "entity_id": str(uuid4()),
                    "amount": amt,
                    "timestamp": _iso(base + timedelta(seconds=10 + i)),
                    "metadata": meta,
                },
            )
        )

    for j in range(40):
        rows.append(
            SeedRow(
                "allow",
                None,
                {
                    "entity_id": str(uuid4()),
                    "amount": round(1.0 + (j % 50) * 1.17, 2),
                    "timestamp": _iso(base + timedelta(seconds=30 + j)),
                    "metadata": {
                        "seed": "beta",
                        "cohort": "benign",
                        "seq": j,
                        "merchant_category": "5411",
                    },
                },
            )
        )

    assert len(rows) == 50
    return rows


def _expected_ui_status(rule_actions: list[str], body: dict[str, Any]) -> str:
    if "BLOCK" in rule_actions:
        return "BLOCK"
    if "SHADOW_REVIEW" in rule_actions:
        if body.get("shadow_agent"):
            return "SHADOW_REVIEW"
        if body.get("orchestrator_fallback_decision") == "FLAG":
            return "FLAG"
        return "SHADOW_REVIEW"
    return "ALLOW"


def _post_json(url: str, body: dict[str, Any], timeout_s: float) -> tuple[int, str, dict[str, Any] | None]:
    data = json.dumps(body, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode() or 200
            try:
                parsed: dict[str, Any] | None = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            return code, raw, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return int(exc.code), raw, parsed


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed 50 beta transactions via Orchestrator ingest.")
    ap.add_argument(
        "--url",
        default=os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8790/v1/ingest"),
        help="Orchestrator ingest URL",
    )
    ap.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout seconds")
    ap.add_argument(
        "--manifest",
        type=Path,
        default=Path("artifacts") / "seed_beta_manifest.json",
        help="Write JSON manifest for ticker / audit QA",
    )
    ap.add_argument("--dry-run", action="store_true", help="Build rows and print plan; no HTTP")
    args = ap.parse_args()

    rows = build_seed_rows()
    if args.dry_run:
        print(f"dry-run: {len(rows)} rows (block={sum(1 for r in rows if r.kind=='block')}, "
              f"shadow={sum(1 for r in rows if r.kind=='shadow')}, "
              f"allow={sum(1 for r in rows if r.kind=='allow')})")
        return 0

    manifest: list[dict[str, Any]] = []
    ok = 0
    fail = 0
    for row in rows:
        code, raw, parsed = _post_json(args.url, row.payload, args.timeout)
        rule_actions: list[str] = []
        if parsed and isinstance(parsed.get("rule_engine"), dict):
            acts = parsed["rule_engine"].get("actions")
            if isinstance(acts, list):
                rule_actions = [str(a) for a in acts]
        ui_status = _expected_ui_status(rule_actions, parsed or {}) if parsed else "ERROR"
        tid = str((parsed or {}).get("transaction_id") or row.payload["entity_id"])
        manifest.append(
            {
                "kind": row.kind,
                "fraud_pattern": row.fraud_pattern,
                "entity_id": row.payload["entity_id"],
                "transaction_id": tid,
                "amount": row.payload["amount"],
                "http_status": code,
                "rule_engine_actions": rule_actions,
                "expected_ticker_status": ui_status,
                "has_shadow_agent": bool(parsed and parsed.get("shadow_agent")),
                "orchestrator_fallback": parsed.get("orchestrator_fallback_reason") if parsed else None,
            }
        )
        if 200 <= code < 300:
            ok += 1
        else:
            fail += 1
            print(f"WARN: HTTP {code} kind={row.kind} entity={row.payload['entity_id']}: {raw[:300]!r}", file=sys.stderr)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "orchestrator_url": args.url,
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(rows),
        "http_2xx": ok,
        "http_errors": fail,
        "rows": manifest,
    }
    args.manifest.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"seed_beta_data: wrote {args.manifest}  OK={ok}  FAIL={fail}  total={len(rows)}")
    if fail:
        print(
            "Hint: SHADOW rows need SHADOW_AGENT_URL + SHADOW_API_KEY on the orchestrator; "
            "otherwise orchestrator returns 503 for SHADOW_REVIEW.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
