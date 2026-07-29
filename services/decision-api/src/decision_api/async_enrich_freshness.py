"""Async enrich cache freshness (CQRS lag budget on evaluate read path)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

log = logging.getLogger("decision-api.async_enrich")

FreshnessAction = Literal["ok", "stale", "missing_ts"]


@dataclass(frozen=True)
class AsyncEnrichFreshnessResult:
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


def evaluate_async_enrich_freshness(
    blob: dict[str, Any],
    *,
    max_age_minutes: int,
    tenant_id: str = "",
    entity_id: str = "",
) -> AsyncEnrichFreshnessResult:
    """Check Redis async-OSINT blob ``updated_at`` against the lag budget.

    ``max_age_minutes <= 0`` disables the check (always ``ok``).
    """
    if max_age_minutes <= 0:
        return AsyncEnrichFreshnessResult(action="ok")
    raw = blob.get("updated_at") or blob.get("as_of") or blob.get("graph_data_as_of")
    if not raw:
        return AsyncEnrichFreshnessResult(action="missing_ts")
    as_of = _parse_iso_utc(raw)
    if as_of is None:
        log.debug(
            "async_enrich_freshness_unparseable tenant_id=%s entity_id=%s updated_at=%r",
            tenant_id,
            entity_id,
            raw,
        )
        return AsyncEnrichFreshnessResult(action="missing_ts")
    age_minutes = (datetime.now(UTC) - as_of).total_seconds() / 60.0
    if age_minutes <= max_age_minutes:
        return AsyncEnrichFreshnessResult(action="ok", age_minutes=age_minutes)
    log.warning(
        "async_enrich_stale tenant_id=%s entity_id=%s age_minutes=%.1f max_age_minutes=%s",
        tenant_id,
        entity_id,
        age_minutes,
        max_age_minutes,
    )
    return AsyncEnrichFreshnessResult(action="stale", age_minutes=age_minutes)
