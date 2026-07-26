"""Graph entity-risk freshness: warn / skip / fail-closed by event_type."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

log = logging.getLogger("decision-api.graph_risk")

FreshnessAction = Literal["ok", "warn", "skip", "fail_closed"]


@dataclass(frozen=True)
class GraphFreshnessResult:
    action: FreshnessAction
    age_minutes: float | None = None


def _parse_iso_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_freshness_policy_by_event(raw: str | None) -> dict[str, FreshnessAction]:
    """Parse ``payment:fail_closed,login:skip`` into a map."""
    out: dict[str, FreshnessAction] = {}
    if not raw or not str(raw).strip():
        return out
    allowed = {"warn", "skip", "fail_closed"}
    for part in str(raw).split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        et, action = part.split(":", 1)
        et = et.strip().lower()
        action = action.strip().lower()
        if et and action in allowed:
            out[et] = action  # type: ignore[assignment]
    return out


def evaluate_graph_risk_freshness(
    payload: dict[str, Any],
    *,
    max_age_minutes: int,
    tenant_id: str,
    entity_id: str,
    event_type: str | None = None,
    default_policy: FreshnessAction = "warn",
    policy_by_event_type: dict[str, FreshnessAction] | None = None,
    metrics_inc: Any | None = None,
) -> GraphFreshnessResult:
    """Decide freshness action for a graph entity-risk payload.

    ``max_age_minutes <= 0`` disables the check (always ``ok``).
    """
    if max_age_minutes <= 0:
        return GraphFreshnessResult(action="ok")
    raw = payload.get("graph_data_as_of")
    if not raw:
        return GraphFreshnessResult(action="ok")
    as_of = _parse_iso_utc(raw)
    if as_of is None:
        log.warning(
            "graph_risk_freshness_unparseable tenant_id=%s entity_id=%s graph_data_as_of=%r",
            tenant_id,
            entity_id,
            raw,
        )
        return GraphFreshnessResult(action="ok")
    age_minutes = (datetime.now(UTC) - as_of).total_seconds() / 60.0
    if age_minutes <= max_age_minutes:
        return GraphFreshnessResult(action="ok", age_minutes=age_minutes)

    et = (event_type or "").strip().lower()
    policy_map = policy_by_event_type or {}
    policy: FreshnessAction = policy_map.get(et, default_policy)
    if policy not in ("warn", "skip", "fail_closed"):
        policy = "warn"

    log.warning(
        "graph_risk_stale tenant_id=%s entity_id=%s event_type=%s policy=%s "
        "age_minutes=%.1f max_age_minutes=%s graph_checkpoint=%s graph_data_as_of=%s",
        tenant_id,
        entity_id,
        et or "-",
        policy,
        age_minutes,
        max_age_minutes,
        payload.get("graph_checkpoint"),
        raw,
    )
    if metrics_inc is not None:
        try:
            metrics_inc("tarka_graph_risk_stale_total")
        except Exception:
            log.debug("graph_risk_stale_metric_failed", exc_info=True)
    return GraphFreshnessResult(action=policy, age_minutes=age_minutes)


def warn_if_graph_risk_stale(
    payload: dict[str, Any],
    *,
    max_age_minutes: int,
    tenant_id: str,
    entity_id: str,
    metrics_inc: Any | None = None,
) -> float | None:
    """Backward-compatible warn-only helper. Returns age minutes when stale."""
    result = evaluate_graph_risk_freshness(
        payload,
        max_age_minutes=max_age_minutes,
        tenant_id=tenant_id,
        entity_id=entity_id,
        default_policy="warn",
        metrics_inc=metrics_inc,
    )
    if result.action == "ok":
        return None
    return result.age_minutes
