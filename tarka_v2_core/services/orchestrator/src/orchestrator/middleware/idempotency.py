"""Redis-backed idempotency locks for async orchestrator handlers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_LOCK_VALUE = "1"
_MAX_KEY_LEN = 512
_MAX_TTL_SEC = 86_400 * 30  # 30 days


class IdempotencyKeyError(ValueError):
    """Raised when an idempotency key or TTL is invalid."""


def _normalize_key(key: str) -> str:
    token = (key or "").strip()
    if not token:
        raise IdempotencyKeyError("idempotency key must be a non-empty string")
    if len(token) > _MAX_KEY_LEN:
        raise IdempotencyKeyError(
            f"idempotency key exceeds {_MAX_KEY_LEN} characters (got {len(token)})",
        )
    if "\x00" in token:
        raise IdempotencyKeyError("idempotency key must not contain NUL bytes")
    return token


def _normalize_ttl(ttl_seconds: int) -> int:
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise IdempotencyKeyError(f"ttl_seconds must be an integer, got {ttl_seconds!r}") from exc
    if ttl <= 0:
        raise IdempotencyKeyError(f"ttl_seconds must be > 0, got {ttl}")
    return min(ttl, _MAX_TTL_SEC)


async def verify_and_lock_event(
    redis_client: Any,
    key: str,
    ttl_seconds: int = 3600,
) -> bool:
    """
    Acquire a Redis idempotency lock via atomic ``SET key value NX EX ttl``.

    Returns ``True`` when the lock is acquired (first-seen event). Returns ``False`` when the key
    already exists (duplicate or in-flight handler). Raises :class:`IdempotencyKeyError` for invalid
    inputs and :class:`RuntimeError` when ``redis_client`` is missing.
    """
    if redis_client is None:
        raise RuntimeError("redis_client is required for verify_and_lock_event")

    norm_key = _normalize_key(key)
    ex = _normalize_ttl(ttl_seconds)

    acquired = await redis_client.set(norm_key, _LOCK_VALUE, nx=True, ex=ex)
    if acquired is True:
        logger.debug("idempotency_lock_acquired key=%s ttl_sec=%s", norm_key, ex)
        return True

    logger.debug("idempotency_lock_duplicate key=%s", norm_key)
    return False


async def release_lock(redis_client: Any, key: str) -> bool:
    """
    Explicitly remove an idempotency lock (``DEL key``).

    Use when an unrecoverable handler failure should allow a later retry with the same idempotency
    key before the TTL expires. Returns ``True`` when a key was deleted.
    """
    if redis_client is None:
        raise RuntimeError("redis_client is required for release_lock")

    norm_key = _normalize_key(key)
    deleted = await redis_client.delete(norm_key)
    removed = int(deleted or 0) > 0
    if removed:
        logger.debug("idempotency_lock_released key=%s", norm_key)
    else:
        logger.debug("idempotency_lock_release_noop key=%s", norm_key)
    return removed
