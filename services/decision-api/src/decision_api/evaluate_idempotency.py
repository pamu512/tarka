"""Atomic idempotency for POST /v1/decisions/evaluate."""

from __future__ import annotations

import json
import logging
from typing import Any

from decision_api.redis_store import redis_tags

log = logging.getLogger("decision-api.idempotency")

_PREFIX = "eval_idem:"
_DEFAULT_TTL = 86400


async def claim_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    ttl_seconds: int = _DEFAULT_TTL,
) -> tuple[bool, dict[str, Any] | None]:
    """Atomically claim an idempotency key.

    Returns ``(True, None)`` when this request owns the key (first writer).
    Returns ``(False, cached)`` when a prior response is stored.
    Returns ``(False, None)`` when another request is in-flight (caller should 409).
    """
    key = f"{_PREFIX}{tenant_id}:{idempotency_key.strip()[:256]}"
    ex = max(1, int(ttl_seconds))
    await redis_tags.connect()
    marker = json.dumps({"status": "in_flight"}, separators=(",", ":"))
    if redis_tags._client:
        created = await redis_tags._client.set(key, marker, ex=ex, nx=True)
        if created:
            return True, None
        raw = await redis_tags._client.get(key)
        if not raw:
            return False, None
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return False, None
        if isinstance(payload, dict) and payload.get("status") == "done":
            body = payload.get("response")
            return False, body if isinstance(body, dict) else None
        return False, None
    if redis_tags._kv:
        async with redis_tags._async_lock:
            existing = await redis_tags._kv.get(key)
            if existing:
                try:
                    payload = json.loads(existing)
                except (TypeError, json.JSONDecodeError):
                    return False, None
                if isinstance(payload, dict) and payload.get("status") == "done":
                    body = payload.get("response")
                    return False, body if isinstance(body, dict) else None
                return False, None
            await redis_tags._kv.set(key, marker, ttl_seconds=ex)
            return True, None
    # No store: fail open for local single-process demos (header still required when configured).
    log.warning("evaluate_idempotency_store_unavailable tenant_id=%s", tenant_id)
    return True, None


async def complete_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    response: dict[str, Any],
    ttl_seconds: int = _DEFAULT_TTL,
) -> None:
    key = f"{_PREFIX}{tenant_id}:{idempotency_key.strip()[:256]}"
    ex = max(1, int(ttl_seconds))
    blob = json.dumps(
        {"status": "done", "response": response},
        separators=(",", ":"),
        default=str,
    )
    await redis_tags.connect()
    if redis_tags._client:
        await redis_tags._client.set(key, blob, ex=ex)
        return
    if redis_tags._kv:
        async with redis_tags._async_lock:
            await redis_tags._kv.set(key, blob, ttl_seconds=ex)
