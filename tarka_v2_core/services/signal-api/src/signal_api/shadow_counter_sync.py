"""
Redis shadow-hypothesis counters on unified signal ingest (Prompt 190).

Active observation rules are read from ``shadow:rules:active`` (JSON list of rules or packs).
Each matching rule increments ``stats:shadow:{rule_id}:matches`` in a single pipeline round-trip.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema
from tarka_v2_core.shadow_hypothesis import (
    SHADOW_RULES_ACTIVE_KEY,
    iter_active_shadow_rules,
    matched_shadow_rule_ids,
    shadow_match_stats_key,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SHADOW_RULES_ACTIVE_KEY",
    "shadow_match_stats_key",
    "features_from_signal",
    "sync_shadow_match_counters",
]


def _shadow_rules_cache_ttl_sec() -> float:
    raw = (os.environ.get("SIGNAL_SHADOW_RULES_CACHE_SEC") or "5").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 5.0


def features_from_signal(body: UnifiedSignalSchema) -> dict[str, Any]:
    """Feature map for shadow rule predicates (flat ``when`` / Rust ``when_ast``)."""
    return {
        "canvas_hash": body.canvas_hash,
        "webgl_vendor": body.webgl_vendor,
        "device_memory": body.device_memory,
        "client_ip": str(body.client_ip),
        "is_proxy": body.is_proxy,
        "user_agent": body.user_agent,
        "session_id": str(body.session_id),
        "timestamp": body.timestamp.isoformat(),
        "sdk_version": body.sdk_version,
        "mouse_velocity": body.mouse_velocity,
        "touch_points": body.touch_points,
        "is_headless": body.is_headless,
        "geo_country_code": body.geo_country_code,
        "geo_city_name": body.geo_city_name,
    }


async def _load_active_shadow_rules_from_redis(redis: Any) -> list[dict[str, Any]]:
    raw = await redis.get(SHADOW_RULES_ACTIVE_KEY)
    if not raw:
        return []
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("shadow_rules_active_invalid_json key=%s", SHADOW_RULES_ACTIVE_KEY)
        return []
    return iter_active_shadow_rules(blob)


async def load_active_shadow_rules(
    redis: Any,
    app_state: Any | None = None,
) -> list[dict[str, Any]]:
    """Load active shadow rules with optional short TTL cache on ``app.state``."""
    ttl = _shadow_rules_cache_ttl_sec()
    if app_state is not None and ttl > 0:
        cached = getattr(app_state, "shadow_rules_active", None)
        cached_at = float(getattr(app_state, "shadow_rules_active_cached_at", 0.0) or 0.0)
        if isinstance(cached, list) and (time.monotonic() - cached_at) < ttl:
            return list(cached)

    rules = await _load_active_shadow_rules_from_redis(redis)
    if app_state is not None and ttl > 0:
        app_state.shadow_rules_active = rules
        app_state.shadow_rules_active_cached_at = time.monotonic()
    return rules


async def sync_shadow_match_counters(
    redis: Any,
    body: UnifiedSignalSchema,
    *,
    app_state: Any | None = None,
) -> list[str]:
    """
    Evaluate active shadow rules against ``body`` and increment match counters via Redis pipeline.

    Returns the list of rule ids that matched (empty when none or registry unset).
    """
    rules = await load_active_shadow_rules(redis, app_state)
    if not rules:
        return []

    features = features_from_signal(body)
    matched = matched_shadow_rule_ids(rules, features)
    if not matched:
        return []

    pipe: Any = redis.pipeline(transaction=False)
    for rid in matched:
        pipe.incr(shadow_match_stats_key(rid))
    await pipe.execute()

    logger.debug(
        "shadow_match_counters_incremented session_id=%s rule_ids=%s",
        body.session_id,
        matched,
    )
    return matched
