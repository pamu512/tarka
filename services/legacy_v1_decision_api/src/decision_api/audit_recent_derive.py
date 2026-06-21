"""Rule-result derivation for recent audit ticker rows (no ORM imports)."""

from __future__ import annotations

from typing import Any


def derive_rule_result(
    decision: str, tags: list[Any] | None, snap: dict[str, Any]
) -> str:
    """Map persisted audit to a coarse rule outcome for ticker UIs."""
    rr = snap.get("rule_result")
    if isinstance(rr, str):
        u = rr.strip().upper()
        if u in {"ALLOW", "DENY", "REVIEW", "SHADOW_REVIEW"}:
            return u
    tags_l = [str(t).lower() for t in (tags or [])]
    if any(
        "shadow_review" in t or t in {"shadow:review", "shadow_review"} for t in tags_l
    ):
        return "SHADOW_REVIEW"
    pr = snap.get("policy_routing")
    if isinstance(pr, dict) and pr.get("decisions_agree") is False:
        ch = str(pr.get("challenger_decision") or "").lower()
        champ = str(pr.get("champion_decision") or "").lower()
        if ch == "review" and champ == "allow":
            return "SHADOW_REVIEW"
    d = str(decision).lower()
    if d == "allow":
        return "ALLOW"
    if d == "deny":
        return "DENY"
    return "REVIEW"
