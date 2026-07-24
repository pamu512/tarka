"""Warn when graph-service entity-risk data is older than the configured bound."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("decision-api.graph_risk")


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


def warn_if_graph_risk_stale(
    payload: dict[str, Any],
    *,
    max_age_minutes: int,
    tenant_id: str,
    entity_id: str,
    metrics_inc: Any | None = None,
) -> float | None:
    """Log + metric when ``graph_data_as_of`` exceeds ``max_age_minutes``.

    Returns age in minutes when stale, else ``None``. ``max_age_minutes <= 0`` disables the check.
    """
    if max_age_minutes <= 0:
        return None
    raw = payload.get("graph_data_as_of")
    if not raw:
        return None
    as_of = _parse_iso_utc(raw)
    if as_of is None:
        log.warning(
            "graph_risk_freshness_unparseable tenant_id=%s entity_id=%s graph_data_as_of=%r",
            tenant_id,
            entity_id,
            raw,
        )
        return None
    age_minutes = (datetime.now(UTC) - as_of).total_seconds() / 60.0
    if age_minutes <= max_age_minutes:
        return None
    log.warning(
        "graph_risk_stale tenant_id=%s entity_id=%s age_minutes=%.1f max_age_minutes=%s graph_checkpoint=%s graph_data_as_of=%s",
        tenant_id,
        entity_id,
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
    return age_minutes
