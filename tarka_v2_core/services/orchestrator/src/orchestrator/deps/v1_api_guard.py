"""Shared FastAPI dependencies for protected ``/v1`` orchestrator routes."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from orchestrator.anumana_browser_ingest import ingress_client_ip

logger = logging.getLogger(__name__)

_DEFAULT_V1_RATE_LIMIT_RPM = 120
_RATE_LIMIT_WINDOW_SEC = 60.0


class MinuteRateLimiter:
    """In-process sliding-window limiter (per key)."""

    __slots__ = ("max_events", "window", "_dq", "_lock")

    def __init__(self, max_events: int, window: float = _RATE_LIMIT_WINDOW_SEC) -> None:
        self.max_events = max(1, int(max_events))
        self.window = float(window)
        self._dq: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._dq[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_events:
                return False
            bucket.append(now)
            return True


def resolve_v1_auth_token_secret() -> str | None:
    """Configured bearer for ``X-Auth-Token`` verification (``None`` = presence-only)."""
    for env_key in (
        "ORCHESTRATOR_V1_AUTH_TOKEN",
        "ORCHESTRATOR_AUTORESOLVE_AUTH_TOKEN",
        "SHADOW_API_KEY",
    ):
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            return raw
    return None


def resolve_v1_rate_limit_rpm() -> int:
    raw = (os.environ.get("ORCHESTRATOR_V1_RATE_LIMIT_RPM") or "").strip()
    if not raw:
        return _DEFAULT_V1_RATE_LIMIT_RPM
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("orchestrator_v1_rate_limit_rpm_invalid value=%r using_default=%s", raw, _DEFAULT_V1_RATE_LIMIT_RPM)
        return _DEFAULT_V1_RATE_LIMIT_RPM


def build_v1_rate_limiter(*, rpm: int | None = None) -> MinuteRateLimiter | None:
    limit = resolve_v1_rate_limit_rpm() if rpm is None else max(0, int(rpm))
    if limit <= 0:
        return None
    return MinuteRateLimiter(limit)


def _rate_limit_key(request: Request) -> str:
    tok = (request.headers.get("x-auth-token") or request.headers.get("X-Auth-Token") or "").strip()
    if tok:
        digest = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16]
        return f"auth:{digest}"
    client_ip = ingress_client_ip(request) or "unknown"
    return f"ip:{client_ip}"


async def require_v1_auth_token(
    x_auth_token: Annotated[str, Header(alias="X-Auth-Token")],
) -> str:
    """
    Require a non-empty ``X-Auth-Token`` header.

    When ``ORCHESTRATOR_V1_AUTH_TOKEN`` (or autoresolve/shadow fallbacks) is configured, the header
    must match exactly (constant-time compare).
    """
    token = (x_auth_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "missing_auth_token",
                "message": "X-Auth-Token header is required and must be non-empty",
            },
        )

    expected = resolve_v1_auth_token_secret()
    if expected is not None and not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "message": "X-Auth-Token is invalid",
            },
        )
    return token


async def enforce_v1_rate_limit(request: Request) -> None:
    """Apply per-token (or per-IP) sliding-window rate limiting for protected ``/v1`` routes."""
    limiter: MinuteRateLimiter | None = getattr(request.app.state, "v1_rate_limiter", None)
    if limiter is None:
        return

    key = _rate_limit_key(request)
    if limiter.allow(key):
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "rate_limit_exceeded",
            "message": "Too many requests for this API token or client",
        },
        headers={"Retry-After": "60"},
    )


V1_PROTECTED_ROUTE_DEPENDENCIES: list[Any] = [
    Depends(require_v1_auth_token),
    Depends(enforce_v1_rate_limit),
]
