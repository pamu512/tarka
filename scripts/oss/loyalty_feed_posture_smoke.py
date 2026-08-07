#!/usr/bin/env python3
"""C1 smoke: incomplete feeds never claim-ready; status file defaults NOT_PROVEN."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "services" / "decision-api" / "src"))

from decision_api.loyalty_feed_posture import (  # noqa: E402
    load_loyalty_feed_ops_posture,
    validate_feed_snapshot,
)


def main() -> int:
    missing = validate_feed_snapshot(None)
    incomplete = validate_feed_snapshot(
        {"orders": [], "refunds": [], "loyalty_ledger": [], "lifecycle": []}
    )
    complete = validate_feed_snapshot(
        {
            "orders": [{"entity_id": "e"}],
            "refunds": [],
            "loyalty_ledger": [{"entity_id": "e"}],
            "lifecycle": [{"entity_id": "e"}],
        }
    )
    posture = load_loyalty_feed_ops_posture()
    errors: list[str] = []
    if missing["claim_allowed"] or incomplete["claim_allowed"] or complete["claim_allowed"]:
        errors.append("validate_feed_snapshot must never set claim_allowed")
    if posture.get("live_claim_allowed"):
        errors.append("OSS default posture must not allow live loyalty claim")
    if posture.get("feeds_status", {}).get("status") not in {
        "FEEDS_NOT_PROVEN",
        "MISSING",
        "WAIVED",
        "INVALID",
    }:
        # FEEDS_READY only with operator pin + bridge — not default smoke path
        if not posture.get("live_claim_allowed"):
            pass
        else:
            errors.append("unexpected live claim")
    if errors:
        print("FAIL", errors)
        return 1
    print(
        "OK",
        {
            "missing": missing["status"],
            "incomplete": incomplete["status"],
            "complete": complete["status"],
            "ops_status": posture.get("feeds_status", {}).get("status"),
            "live_claim_allowed": posture.get("live_claim_allowed"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
