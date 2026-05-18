"""Load active shadow rules from Redis and evaluate against a transaction envelope."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ingestor.manifest_schema import TransactionSchema
from tarka_v2_core.shadow_hypothesis import (
    SHADOW_RULES_ACTIVE_KEY,
    evaluate_shadow_matches_from_rules,
    iter_active_shadow_rules,
)

logger = logging.getLogger(__name__)


def resolve_shadow_rules_redis_url() -> str | None:
    for key in (
        "SHADOW_RULES_REDIS_URL",
        "ANUMANA_TELEMETRY_REDIS_URL",
        "ANUMANA_REDIS_URL",
        "SIGNAL_REDIS_URL",
    ):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return None


def features_from_transaction(transaction: TransactionSchema) -> dict[str, Any]:
    meta = dict(transaction.metadata) if transaction.metadata else {}
    return {
        "entity_id": str(transaction.entity_id),
        "amount": transaction.amount,
        "timestamp": transaction.timestamp.isoformat(),
        "country": transaction.country,
        **meta,
    }


def _shadow_rules_cache_ttl_sec() -> float:
    raw = (os.environ.get("SHADOW_RULES_CACHE_SEC") or "5").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 5.0


async def _load_active_shadow_rules(redis: Any, app_state: Any | None) -> list[dict[str, Any]]:
    ttl = _shadow_rules_cache_ttl_sec()
    if app_state is not None and ttl > 0:
        cached = getattr(app_state, "shadow_rules_active", None)
        cached_at = float(getattr(app_state, "shadow_rules_active_cached_at", 0.0) or 0.0)
        if isinstance(cached, list) and (time.monotonic() - cached_at) < ttl:
            return list(cached)

    raw = await redis.get(SHADOW_RULES_ACTIVE_KEY)
    if not raw:
        rules: list[dict[str, Any]] = []
    else:
        try:
            rules = iter_active_shadow_rules(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("shadow_rules_active_invalid_json key=%s", SHADOW_RULES_ACTIVE_KEY)
            rules = []

    if app_state is not None and ttl > 0:
        app_state.shadow_rules_active = rules
        app_state.shadow_rules_active_cached_at = time.monotonic()
    return rules


async def _redis_for_shadow_rules(app_state: Any) -> Any | None:
    existing = getattr(app_state, "shadow_rules_redis", None)
    if existing is not None:
        return existing
    url = getattr(app_state, "shadow_rules_redis_url", None) or resolve_shadow_rules_redis_url()
    if not url:
        return None
    import redis.asyncio as redis_mod

    client = redis_mod.from_url(url, decode_responses=True)
    app_state.shadow_rules_redis = client
    app_state.shadow_rules_redis_url = url
    return client


async def evaluate_transaction_shadow_matches(
    app_state: Any,
    transaction: TransactionSchema,
) -> list[dict[str, Any]]:
    """
    Evaluate all active shadow hypotheses for ``transaction``.

    Returns JSON-serializable rows for ``audit_logs.shadow_matches`` (empty when Redis or rules unset).
    """
    redis = await _redis_for_shadow_rules(app_state)
    if redis is None:
        return []
    rules = await _load_active_shadow_rules(redis, app_state)
    if not rules:
        return []
    features = features_from_transaction(transaction)
    return evaluate_shadow_matches_from_rules(rules, features)
