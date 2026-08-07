#!/usr/bin/env python3
"""Prove vertical promote_gate / kill_criteria blocks underpowered shadow metrics.

Exit 0 when gate correctly blocks bad metrics and allows good metrics.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "decision-api" / "src"))

from decision_api.vertical_packs import evaluate_kill_criteria, get_vertical_pack  # noqa: E402


def main() -> int:
    pack = get_vertical_pack("fintech")
    if not pack or not pack.get("kill_criteria"):
        print("shadow_promote_gate_smoke: FAIL — fintech pack missing kill_criteria", file=sys.stderr)
        return 1
    criteria = pack["kill_criteria"]

    blocked = evaluate_kill_criteria(
        {"precision": 0.01, "recall": 0.01, "false_positive_rate": 0.5},
        criteria,
        events_evaluated=5,
    )
    if blocked.get("promote_allowed") is not False:
        print("shadow_promote_gate_smoke: FAIL — expected underpowered metrics to block", file=sys.stderr)
        print(blocked, file=sys.stderr)
        return 1

    allowed = evaluate_kill_criteria(
        {
            "precision": float(criteria.get("min_precision", 0.5)) + 0.2,
            "recall": float(criteria.get("min_recall", 0.5)) + 0.2,
            "false_positive_rate": max(0.0, float(criteria.get("max_false_positive_rate", 0.2)) - 0.05),
        },
        criteria,
        events_evaluated=int(criteria.get("min_events", 100)) + 50,
    )
    if allowed.get("promote_allowed") is not True:
        print("shadow_promote_gate_smoke: FAIL — expected healthy metrics to promote", file=sys.stderr)
        print(allowed, file=sys.stderr)
        return 1

    print("shadow_promote_gate_smoke: OK (block underpowered + allow healthy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
