#!/usr/bin/env python3
"""Track B: S9 loyalty feed fixture smoke — complete gates; incomplete never eligible.

Not live tenant warehouse proof. Uses pinned ``now`` from the fixture pack.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "loyalty_economics_cases.json"
_SCHEMA = "tarka.loyalty_economics_gates/v1"


def _parse_now(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _any_eligible_true(gates: dict[str, Any]) -> bool:
    for g in gates.values():
        if isinstance(g, dict) and g.get("eligible") is True:
            return True
    return False


def run_cases(pack: dict[str, Any]) -> dict[str, Any]:
    sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
    from decision_api.loyalty_economics import evaluate_loyalty_economics

    now = _parse_now(str(pack["now"]))
    cfg = pack["program_config"]
    results: list[dict[str, Any]] = []
    ok_all = True

    for case in pack.get("cases") or []:
        if not isinstance(case, dict):
            ok_all = False
            results.append({"id": "?", "ok": False, "error": "invalid case"})
            continue
        cid = str(case.get("id") or "?")
        out = evaluate_loyalty_economics(
            entity_id=str(case["entity_id"]),
            feed_snapshot=case.get("feed_snapshot"),
            program_config=cfg,
            now=now,
        )
        gates = out.get("gates") or {}
        order = gates.get("order") or {}
        errors: list[str] = []

        if out.get("schema_id") != _SCHEMA:
            errors.append("bad schema_id")
        if out.get("policy", {}).get("order_decision_untouched") is not True:
            errors.append("order_decision_untouched missing")

        expect_status = case.get("expect_status") or []
        if expect_status and out.get("status") not in expect_status:
            errors.append(f"status={out.get('status')} not in {expect_status}")

        if "expect_order_eligible" in case:
            exp = case["expect_order_eligible"]
            if order.get("eligible") is not exp:
                errors.append(f"order.eligible={order.get('eligible')} want {exp}")

        for gate_name, key in (
            ("dispatch", "expect_dispatch_eligible"),
            ("redeem", "expect_redeem_eligible"),
        ):
            if key in case:
                got = (gates.get(gate_name) or {}).get("eligible")
                if got is not case[key]:
                    errors.append(f"{gate_name}.eligible={got} want {case[key]}")

        if case.get("expect_no_eligible_true") and _any_eligible_true(gates):
            errors.append("eligible:true forbidden when feeds incomplete")

        if case.get("expect_any_eligible_true") is False and _any_eligible_true(gates):
            errors.append("abuse case must not have eligible:true")

        case_ok = not errors
        ok_all = ok_all and case_ok
        results.append(
            {
                "id": cid,
                "ok": case_ok,
                "status": out.get("status"),
                "order_eligible": order.get("eligible"),
                "errors": errors,
            }
        )

    return {
        "ok": ok_all,
        "schema_id": "tarka.loyalty_economics_feed_smoke/v1",
        "cases": results,
        "fixture": str(_FIXTURE.relative_to(_REPO)),
    }


def main() -> int:
    pack = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report = run_cases(pack)
    print(json.dumps(report, indent=2))
    art = os.environ.get("LOYALTY_ECONOMICS_ARTIFACT", "").strip()
    if art:
        path = Path(art)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
