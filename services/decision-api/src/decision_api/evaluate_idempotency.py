"""Atomic idempotency for POST /v1/decisions/evaluate."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any

from decision_api.redis_store import redis_tags

log = logging.getLogger("decision-api.idempotency")

_PREFIX = "eval_idem:"
_DEFAULT_RESULT_TTL = 86400
_DEFAULT_CLAIM_LEASE = 30


@dataclass(frozen=True)
class EvaluateIdempotencyClaim:
    state: str
    response: dict[str, Any] | None = None
    owner_token: str | None = None


def canonical_request_fingerprint(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_key(tenant_id: str, idempotency_key: str) -> str:
    scoped = f"{tenant_id}\0{idempotency_key.strip()[:256]}".encode("utf-8")
    return f"{_PREFIX}{hashlib.sha256(scoped).hexdigest()}"


def _decode(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _existing_claim(
    payload: dict[str, Any] | None,
    request_fingerprint: str,
) -> EvaluateIdempotencyClaim:
    if payload is None:
        return EvaluateIdempotencyClaim("in_flight")
    if payload.get("request_fingerprint") != request_fingerprint:
        return EvaluateIdempotencyClaim("mismatch")
    if payload.get("status") == "done":
        response = payload.get("response")
        return EvaluateIdempotencyClaim(
            "completed",
            response=response if isinstance(response, dict) else None,
        )
    return EvaluateIdempotencyClaim("in_flight")


async def claim_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    lease_seconds: int = _DEFAULT_CLAIM_LEASE,
) -> EvaluateIdempotencyClaim:
    """Atomically claim a request-bound key with a short in-flight lease."""
    key = _cache_key(tenant_id, idempotency_key)
    ex = max(1, int(lease_seconds))
    owner_token = secrets.token_hex(16)
    await redis_tags.connect()
    marker = json.dumps(
        {
            "status": "in_flight",
            "request_fingerprint": request_fingerprint,
            "owner_token": owner_token,
        },
        separators=(",", ":"),
    )
    if redis_tags._client:
        created = await redis_tags._client.set(key, marker, ex=ex, nx=True)
        if created:
            return EvaluateIdempotencyClaim("owned", owner_token=owner_token)
        raw = await redis_tags._client.get(key)
        return _existing_claim(_decode(raw), request_fingerprint)
    if redis_tags._kv:
        async with redis_tags._async_lock:
            existing = await redis_tags._kv.get(key)
            if existing:
                return _existing_claim(_decode(existing), request_fingerprint)
            await redis_tags._kv.set(key, marker, ttl_seconds=ex)
            return EvaluateIdempotencyClaim("owned", owner_token=owner_token)
    # No store: fail open for local single-process demos (header still required when configured).
    log.warning("evaluate_idempotency_store_unavailable tenant_id=%s", tenant_id)
    return EvaluateIdempotencyClaim("owned", owner_token=owner_token)


async def complete_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    owner_token: str,
    response: dict[str, Any],
    ttl_seconds: int = _DEFAULT_RESULT_TTL,
) -> bool:
    key = _cache_key(tenant_id, idempotency_key)
    ex = max(1, int(ttl_seconds))
    blob = json.dumps(
        {
            "status": "done",
            "request_fingerprint": request_fingerprint,
            "response": response,
        },
        separators=(",", ":"),
        default=str,
    )
    await redis_tags.connect()
    if redis_tags._client:
        changed = await redis_tags._client.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if not current then return 0 end
            local decoded = cjson.decode(current)
            if decoded.status ~= 'in_flight'
              or decoded.request_fingerprint ~= ARGV[1]
              or decoded.owner_token ~= ARGV[2] then
              return 0
            end
            redis.call('SET', KEYS[1], ARGV[3], 'EX', ARGV[4])
            return 1
            """,
            1,
            key,
            request_fingerprint,
            owner_token,
            blob,
            ex,
        )
        return bool(changed)
    if redis_tags._kv:
        async with redis_tags._async_lock:
            current = _decode(await redis_tags._kv.get(key))
            if (
                current is None
                or current.get("status") != "in_flight"
                or current.get("request_fingerprint") != request_fingerprint
                or current.get("owner_token") != owner_token
            ):
                return False
            await redis_tags._kv.set(key, blob, ttl_seconds=ex)
            return True
    return False


async def renew_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    owner_token: str,
    lease_seconds: int = _DEFAULT_CLAIM_LEASE,
) -> bool:
    """Extend only the matching owner's active in-flight lease."""
    key = _cache_key(tenant_id, idempotency_key)
    ex = max(1, int(lease_seconds))
    await redis_tags.connect()
    if redis_tags._client:
        changed = await redis_tags._client.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if not current then return 0 end
            local decoded = cjson.decode(current)
            if decoded.status ~= 'in_flight'
              or decoded.request_fingerprint ~= ARGV[1]
              or decoded.owner_token ~= ARGV[2] then
              return 0
            end
            return redis.call('EXPIRE', KEYS[1], ARGV[3])
            """,
            1,
            key,
            request_fingerprint,
            owner_token,
            ex,
        )
        return bool(changed)
    if redis_tags._kv:
        async with redis_tags._async_lock:
            current = _decode(await redis_tags._kv.get(key))
            if (
                current is None
                or current.get("status") != "in_flight"
                or current.get("request_fingerprint") != request_fingerprint
                or current.get("owner_token") != owner_token
            ):
                return False
            await redis_tags._kv.set(
                key,
                json.dumps(current, separators=(",", ":")),
                ttl_seconds=ex,
            )
            return True
    return False


async def release_evaluate_idempotency(
    *,
    tenant_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    owner_token: str,
) -> bool:
    """Release only the caller's still-active claim after an evaluation failure."""
    key = _cache_key(tenant_id, idempotency_key)
    await redis_tags.connect()
    if redis_tags._client:
        changed = await redis_tags._client.eval(
            """
            local current = redis.call('GET', KEYS[1])
            if not current then return 0 end
            local decoded = cjson.decode(current)
            if decoded.status ~= 'in_flight'
              or decoded.request_fingerprint ~= ARGV[1]
              or decoded.owner_token ~= ARGV[2] then
              return 0
            end
            return redis.call('DEL', KEYS[1])
            """,
            1,
            key,
            request_fingerprint,
            owner_token,
        )
        return bool(changed)
    if redis_tags._kv:
        async with redis_tags._async_lock:
            current = _decode(await redis_tags._kv.get(key))
            if (
                current is None
                or current.get("status") != "in_flight"
                or current.get("request_fingerprint") != request_fingerprint
                or current.get("owner_token") != owner_token
            ):
                return False
            await redis_tags._kv.delete(key)
            return True
    return False
