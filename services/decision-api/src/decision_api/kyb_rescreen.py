"""Continuous KYB re-screen loop (OpenSanctions-class cadence) — no Motiva claim.

Best decision: schedule due sellers from store memory/file; apply hit → collect/suspend.
LIVE OpenSanctions plugin remains the fetch path; this owns the ops loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from decision_api.marketplace_kyb import apply_transition, normalize_state

SCHEMA_ID = "tarka.kyb_rescreen/v1"
METHOD = "rescreen_cadence_v1"
DEFAULT_MAX_AGE_DAYS = 30


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def last_screen_at(record: dict[str, Any]) -> datetime | None:
    for key in (
        "last_rescreen_at",
        "last_screen_at",
        "vendor_verified_at",
        "updated_at",
    ):
        dt = _parse_ts(record.get(key))
        if dt is not None:
            return dt
    return _parse_ts(record.get("created_at"))


def is_due_for_rescreen(
    record: dict[str, Any],
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> bool:
    """Verified/disclosed sellers due when last screen older than max_age_days."""
    state = normalize_state(str(record.get("kyb_state") or ""))
    if state not in ("verified", "disclosed", "disclose_required"):
        return False
    ts = last_screen_at(record)
    if ts is None:
        return True
    now = now or datetime.now(UTC)
    return (now - ts) >= timedelta(days=max(1, int(max_age_days)))


def select_due_sellers(
    records: list[dict[str, Any]],
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    limit: int = 100,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    due = [
        r for r in records if is_due_for_rescreen(r, max_age_days=max_age_days, now=now)
    ]
    due.sort(key=lambda r: last_screen_at(r) or datetime.min.replace(tzinfo=UTC))
    return due[: max(1, min(500, int(limit)))]


def apply_rescreen_result(
    record: dict[str, Any],
    *,
    hit: bool,
    vendor_status: str = "",
    reason: str = "continuous_rescreen",
) -> dict[str, Any]:
    """Apply screening result. Hit → collect (+ suspend if already high-risk)."""
    out = dict(record)
    now = datetime.now(UTC).isoformat()
    out["last_rescreen_at"] = now
    out["updated_at"] = now
    history = list(out.get("rescreen_history") or [])
    history.append(
        {
            "at": now,
            "hit": bool(hit),
            "vendor_status": str(vendor_status)[:128],
            "reason": str(reason)[:256],
        }
    )
    out["rescreen_history"] = history[-50:]
    if hit:
        out["vendor_status"] = str(vendor_status or "hit")[:128]
        state = normalize_state(str(out.get("kyb_state")))
        reports = out.get("suspicious_reports") or []
        try:
            gmv = float(out.get("seller_gmv_30d") or 0)
        except (TypeError, ValueError):
            gmv = 0.0
        escalate = len(reports) >= 1 or gmv >= 5000.0
        try:
            if state in ("verified", "disclosed", "disclose_required"):
                out = apply_transition(
                    out,
                    "collecting",
                    reason=reason,
                    vendor_status=out["vendor_status"],
                )
                state = "collecting"
            if escalate and state == "collecting":
                out = apply_transition(
                    out,
                    "suspended",
                    reason=f"{reason}:hit_escalate",
                    vendor_status=out["vendor_status"],
                )
        except ValueError:
            pass
    else:
        out["vendor_status"] = str(vendor_status or "clear")[:128]
    return out


def rescreen_ops_posture(
    *, due_count: int = 0, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "method": METHOD,
        "motiva_claim_allowed": False,
        "live_claim_allowed": False,
        "max_age_days": max_age_days,
        "due_count": due_count,
        "note": "Cadence loop only — OpenSanctions/identity_kyb plugin does the fetch when creds exist",
    }
