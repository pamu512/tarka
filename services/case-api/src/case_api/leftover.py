"""Leftover predicate — open Hold / evaluate-mint cases with a Person id."""

from datetime import UTC, datetime


def leftover_origin(labels: list[str] | None) -> str:
    labs = {str(x) for x in (labels or [])}
    hold = "act:hold" in labs
    ev = "origin:evaluate" in labs
    if hold and ev:
        return "both"
    if ev:
        return "evaluate"
    return "hold"


def is_leftover(case) -> bool:
    status = str(getattr(case, "status", "") or "").strip().lower()
    if status not in {"open", "investigating"}:
        return False
    if not str(getattr(case, "entity_id", "") or "").strip():
        return False
    labs = {str(x) for x in (getattr(case, "labels", None) or [])}
    return "act:hold" in labs or "origin:evaluate" in labs


def leftover_last_act(case) -> str | None:
    stored = str(getattr(case, "last_act", "") or "").strip() or None
    if stored:
        return stored
    labs = {str(x) for x in (getattr(case, "labels", None) or [])}
    if "act:hold" in labs:
        return "held"
    return None


def leftover_row(case, *, sla_breached: bool) -> dict:
    return {
        "case_id": str(case.id),
        "entity_id": case.entity_id,
        "origin": leftover_origin(getattr(case, "labels", None)),
        "last_outcome": getattr(case, "last_outcome", None),
        "last_act": leftover_last_act(case),
        "claimed_by": getattr(case, "claimed_by", None),
        "sla_breached": bool(sla_breached),
        "trace_id": getattr(case, "trace_id", "") or "",
    }


def actor_from_request(request, user_id: str) -> str:
    hdr = (getattr(request, "headers", None) or {}).get("X-Actor-Id") or ""
    token = str(hdr).strip()
    return token or str(user_id or "").strip() or "anonymous"


def claimed_by_other(case, actor: str) -> str | None:
    other = str(getattr(case, "claimed_by", None) or "").strip()
    if other and other != actor:
        return other
    return None


def apply_claim(case, actor: str, *, now: datetime | None = None) -> None:
    case.claimed_by = actor
    case.claimed_at = now or datetime.now(UTC)


def clear_claim(case) -> None:
    case.claimed_by = None
    case.claimed_at = None
