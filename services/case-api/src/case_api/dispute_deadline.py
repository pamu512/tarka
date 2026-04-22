from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal

"""Deadline / SLA-style countdown helpers for dispute external-response queues (#60)."""

def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def alert_state(
    *,
    deadline: datetime | None,
    reference_start: datetime | None,
    now: datetime,
    near_breach_ratio: float = 0.2,
) -> Literal["no_deadline", "ok", "near_breach", "breached"]:
    if deadline is None:
        return "no_deadline"
    deadline = _aware(deadline)
    now = _aware(now)
    if now >= deadline:
        return "breached"
    ref = reference_start or deadline
    ref = _aware(ref)
    window = (deadline - ref).total_seconds()
    if window <= 0:
        return "breached"
    remaining = (deadline - now).total_seconds()
    thr = max(window * near_breach_ratio, 3600.0)
    if remaining <= thr:
        return "near_breach"
    return "ok"


def queue_item_view(
    dispute: Any,
    *,
    now: datetime,
    near_breach_ratio: float,
) -> dict[str, Any]:
    dl = getattr(dispute, "provider_response_deadline_at", None)
    filed = getattr(dispute, "filed_at", None) or getattr(dispute, "created_at", None)
    st = alert_state(deadline=dl, reference_start=filed, now=now, near_breach_ratio=near_breach_ratio)
    seconds_remaining: int | None = None
    if dl is not None:
        seconds_remaining = max(0, int((_aware(dl) - _aware(now)).total_seconds()))
    hooks: list[str] = []
    if st in ("near_breach", "breached"):
        hooks.append("POST /v1/disputes/{dispute_id}/reprocess-external?tenant_id=... with Idempotency-Key")
    if st == "breached":
        hooks.append("notify: provider_response_deadline_breached")
    if st == "near_breach":
        hooks.append("notify: provider_response_deadline_near_breach")
    return {
        "dispute_id": str(dispute.id),
        "tenant_id": dispute.tenant_id,
        "status": dispute.status,
        "dispute_type": dispute.dispute_type,
        "filed_at": filed.isoformat() if filed else None,
        "provider_response_deadline_at": dl.isoformat() if dl else None,
        "seconds_remaining": seconds_remaining,
        "alert_state": st,
        "suggested_alert_hooks": hooks,
        "external_reprocess_count": int(getattr(dispute, "external_reprocess_count", 0) or 0),
        "last_external_reprocess_at": dispute.last_external_reprocess_at.isoformat() if getattr(dispute, "last_external_reprocess_at", None) else None,
    }
