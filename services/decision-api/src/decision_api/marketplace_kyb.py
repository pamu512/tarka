"""INFORM/DSA-shaped marketplace seller KYB workflow.

Identity verification is a vendor connector; Tarka owns collect → verify →
disclose → suspend_sales state machine and host-action tags.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# INFORM-shaped seller states (US marketplace integrity; DSA-compatible suspend).
KYB_STATES = (
    "unverified",
    "collecting",
    "pending_vendor",
    "verified",
    "disclose_required",
    "disclosed",
    "suspended",
    "rejected",
)

_TRANSITIONS: dict[str, frozenset[str]] = {
    "unverified": frozenset({"collecting", "suspended"}),
    "collecting": frozenset({"pending_vendor", "unverified", "suspended"}),
    "pending_vendor": frozenset({"verified", "rejected", "collecting", "suspended"}),
    # collecting allowed: continuous re-screen hit must force re-KYB
    "verified": frozenset({"disclose_required", "disclosed", "suspended", "collecting"}),
    "disclose_required": frozenset({"disclosed", "suspended"}),
    "disclosed": frozenset({"suspended", "verified", "collecting"}),
    "suspended": frozenset({"collecting", "verified"}),
    "rejected": frozenset({"collecting", "suspended"}),
}

HOST_ACTIONS = {
    "collect_seller_docs": "action:kyb_collect",
    "suspend_sales": "action:suspend_sales",
    "require_disclose": "action:kyb_disclose",
    "release_sales": "action:kyb_release",
}


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_state(state: str | None) -> str:
    s = (state or "unverified").strip().lower()
    return s if s in KYB_STATES else "unverified"


def can_transition(from_state: str, to_state: str) -> bool:
    return normalize_state(to_state) in _TRANSITIONS.get(normalize_state(from_state), frozenset())


def apply_transition(
    record: dict[str, Any],
    to_state: str,
    *,
    reason: str = "",
    vendor_status: str | None = None,
) -> dict[str, Any]:
    """Return updated KYB record or raise ValueError on illegal transition."""
    current = normalize_state(str(record.get("kyb_state") or "unverified"))
    target = normalize_state(to_state)
    if current != target and not can_transition(current, target):
        raise ValueError(f"illegal_kyb_transition:{current}->{target}")
    out = dict(record)
    out["kyb_state"] = target
    out["updated_at"] = _now().isoformat()
    if reason:
        out["last_reason"] = reason[:512]
    if vendor_status is not None:
        out["vendor_status"] = str(vendor_status)[:128]
    history = list(out.get("history") or [])
    history.append(
        {
            "from": current,
            "to": target,
            "at": out["updated_at"],
            "reason": reason[:256] if reason else "",
        }
    )
    out["history"] = history[-50:]
    return out


def evaluate_kyb_gate(
    *,
    kyb_state: str | None,
    seller_gmv_30d: float = 0.0,
    high_volume_threshold: float = 5000.0,
    collect_started_at: str | None = None,
    sla_hours: int = 72,
    vendor_verified: bool = False,
    disclosure_complete: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Policy gate for marketplace sellers (INFORM-shaped thresholds)."""
    state = normalize_state(kyb_state)
    ts = now or _now()
    tags: list[str] = ["vertical:marketplace"]
    host_actions: list[str] = []
    score_delta = 0.0
    blockers: list[str] = []

    high_volume = float(seller_gmv_30d or 0.0) >= float(high_volume_threshold)

    if state == "suspended":
        tags.extend(["risk:kyb_suspended", HOST_ACTIONS["suspend_sales"]])
        host_actions.append("suspend_sales")
        score_delta += 40.0
        blockers.append("seller_suspended")
    elif state == "rejected":
        tags.extend(["risk:kyb_rejected", HOST_ACTIONS["suspend_sales"]])
        host_actions.append("suspend_sales")
        score_delta += 35.0
        blockers.append("kyb_rejected")
    elif high_volume and state in ("unverified", "collecting"):
        tags.extend(["risk:kyb_unverified_high_volume", HOST_ACTIONS["collect_seller_docs"]])
        host_actions.append("collect_seller_docs")
        score_delta += 22.0
        if state == "unverified":
            host_actions.append("suspend_sales")
            tags.append(HOST_ACTIONS["suspend_sales"])
            blockers.append("kyb_required_high_volume")
            score_delta += 10.0
    elif state == "pending_vendor" and not vendor_verified:
        tags.append("risk:kyb_pending")
        score_delta += 8.0
    elif state in ("verified", "disclose_required") and not disclosure_complete:
        tags.extend(["risk:kyb_disclose_required", HOST_ACTIONS["require_disclose"]])
        host_actions.append("require_disclose")
        score_delta += 12.0
        if high_volume:
            tags.append(HOST_ACTIONS["suspend_sales"])
            host_actions.append("suspend_sales")
            blockers.append("disclosure_incomplete")
            score_delta += 15.0
    elif state == "disclosed" or (state == "verified" and disclosure_complete):
        tags.append("kyb:ok")
        if vendor_verified:
            tags.append("kyb:vendor_verified")

    # SLA breach: collecting too long
    if collect_started_at and state in ("collecting", "pending_vendor", "unverified"):
        try:
            started = datetime.fromisoformat(collect_started_at.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if ts - started > timedelta(hours=max(1, sla_hours)):
                tags.extend(["risk:kyb_sla_breach", HOST_ACTIONS["suspend_sales"]])
                host_actions.append("suspend_sales")
                blockers.append("kyb_sla_breach")
                score_delta += 20.0
        except ValueError:
            blockers.append("collect_started_at_invalid")

    # Deduplicate preserving order
    seen: set[str] = set()
    uniq_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq_tags.append(t)
    uniq_actions = list(dict.fromkeys(host_actions))

    return {
        "schema_id": "tarka.marketplace_kyb_gate/v1",
        "kyb_state": state,
        "high_volume": high_volume,
        "tags": uniq_tags,
        "host_actions": uniq_actions,
        "score_delta": score_delta,
        "blockers": blockers,
        "suspend_sales": "suspend_sales" in uniq_actions,
        "note": (
            "Identity docs verified via identity_kyb connector; Tarka owns workflow "
            "and suspend_sales host-action."
        ),
    }


def empty_seller_record(*, tenant_id: str, seller_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "seller_id": seller_id,
        "kyb_state": "unverified",
        "vendor_status": None,
        "disclosure_complete": False,
        "collect_started_at": None,
        "seller_gmv_30d": 0.0,
        "history": [],
        "suspicious_reports": [],
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }


def apply_suspicious_activity_report(
    record: dict[str, Any],
    *,
    report_id: str,
    reporter_id: str = "",
    category: str = "other",
    narrative: str = "",
    force_suspend: bool = False,
) -> dict[str, Any]:
    """INFORM-shaped consumer report → KYB collect (+ optional suspend).

    Distinct from FinCEN SAR filings in case-api — this is marketplace integrity intake.
    """
    out = dict(record)
    reports = list(out.get("suspicious_reports") or [])
    reports.append(
        {
            "report_id": str(report_id)[:128],
            "reporter_id": str(reporter_id)[:128],
            "category": str(category)[:64],
            "narrative": str(narrative)[:2000],
            "at": _now().isoformat(),
        }
    )
    out["suspicious_reports"] = reports[-100:]
    reason = f"suspicious_report:{report_id}"
    state = normalize_state(str(out.get("kyb_state")))
    should_suspend = force_suspend or state == "unverified" or len(reports) >= 3

    if state in ("unverified", "verified", "disclosed"):
        try:
            out = apply_transition(out, "collecting", reason=reason)
        except ValueError:
            pass
        state = normalize_state(str(out.get("kyb_state")))
    if should_suspend and state in ("collecting", "pending_vendor", "unverified"):
        # collecting → suspended is allowed
        try:
            if state == "unverified":
                out = apply_transition(out, "collecting", reason=reason)
            out = apply_transition(out, "suspended", reason=reason)
        except ValueError:
            pass
    if not out.get("collect_started_at"):
        out["collect_started_at"] = _now().isoformat()
    out["updated_at"] = _now().isoformat()
    return out
