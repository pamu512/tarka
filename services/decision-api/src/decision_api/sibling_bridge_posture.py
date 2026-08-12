"""Ops posture for sibling bridges (loyalty / refund / offline-cancel)."""

from __future__ import annotations

from typing import Any

from decision_api.offline_cancel_bridge import (
    bridge_config as cancel_config,
    cancel_circuit_open,
)
from decision_api.refund_abuse_bridge import (
    bridge_config as refund_config,
    refund_circuit_open,
)


def _loyalty_bridge_row(
    *,
    loyalty_abuse_url: str = "",
    loyalty_abuse_api_key: str = "",
) -> dict[str, Any]:
    url = (loyalty_abuse_url or "").strip()
    key = (loyalty_abuse_api_key or "").strip()
    circuit_open = False
    try:
        from decision_api.loyalty_abuse_bridge import loyalty_circuit_open

        circuit_open = bool(loyalty_circuit_open())
    except Exception:
        circuit_open = False
    return {
        "bridge_id": "loyalty_abuse",
        "configured": bool(url),
        "live_claim_allowed": bool(url and key),
        "circuit_open": circuit_open,
        "blockers": (
            ([] if url else ["url_missing"]) + ([] if key else ["api_key_missing"])
        ),
        "checkpoints": ["redeem"],
    }


def load_sibling_bridge_ops_posture(
    *,
    loyalty_abuse_url: str = "",
    loyalty_abuse_api_key: str = "",
) -> dict[str, Any]:
    """Aggregate configured / circuit / blockers for sibling bridges."""
    refund = refund_config()
    cancel = cancel_config()
    bridges = [
        _loyalty_bridge_row(
            loyalty_abuse_url=loyalty_abuse_url,
            loyalty_abuse_api_key=loyalty_abuse_api_key,
        ),
        {
            "bridge_id": "refund_abuse",
            "configured": bool(refund.get("configured")),
            "live_claim_allowed": bool(refund.get("live_claim_allowed")),
            "circuit_open": bool(refund_circuit_open()),
            "blockers": list(refund.get("blockers") or []),
            "checkpoints": ["refund", "return", "chargeback"],
            "advisory": True,
        },
        {
            "bridge_id": "offline_cancel",
            "configured": bool(cancel.get("configured")),
            "live_claim_allowed": bool(cancel.get("live_claim_allowed")),
            "circuit_open": bool(cancel_circuit_open()),
            "blockers": list(cancel.get("blockers") or []),
            "checkpoints": ["cancel", "reassign", "offline_complete"],
        },
    ]
    return {
        "schema_id": "tarka.sibling_bridge_ops/v1",
        "bridges": bridges,
        "any_configured": any(b.get("configured") for b in bridges),
        "any_circuit_open": any(b.get("circuit_open") for b in bridges),
        "live_claim_allowed": False,  # bridges never imply LIVE card/consortium alone
        "honesty": (
            "Sibling bridges are advisory/fail-soft; missing URL → skip, not forge LIVE."
        ),
    }
