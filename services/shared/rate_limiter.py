"""Token-bucket rate limiter middleware using in-memory or Redis backend.

Usage::

    from rate_limiter import setup_rate_limiter
    setup_rate_limiter(app, rpm=600, burst=50)  # 600 req/min, burst of 50
    # Or with Redis:
    setup_rate_limiter(app, rpm=600, burst=50, redis_url="redis://localhost:6379/1")
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

SKIP_PATHS = {"/v1/health", "/metrics"}


class TokenBucket:
    """In-memory per-key token bucket."""
    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> tuple[bool, dict[str, str]]:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self._burst), now))
        elapsed = now - last
        tokens = min(self._burst, tokens + elapsed * self._rate)
        headers = {
            "X-RateLimit-Limit": str(self._burst),
            "X-RateLimit-Remaining": str(max(0, int(tokens) - 1)),
        }
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True, headers
        headers["Retry-After"] = str(int((1 - tokens) / self._rate) + 1)
        self._buckets[key] = (tokens, now)
        return False, headers

    def cleanup(self, max_age: float = 300) -> None:
        now = time.monotonic()
        stale = [k for k, (_, t) in self._buckets.items() if now - t > max_age]
        for k in stale:
            del self._buckets[k]


class RedisTokenBucket:
    """Redis-backed sliding window rate limiter."""
    def __init__(self, redis_url: str, rpm: int, burst: int) -> None:
        self._rpm = rpm
        self._burst = burst
        self._redis_url = redis_url
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as redis
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def allow(self, key: str) -> tuple[bool, dict[str, str]]:
        client = await self._get_client()
        rkey = f"rl:{key}"
        now = time.time()
        window = 60.0
        pipe = client.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - window)
        pipe.zcard(rkey)
        pipe.zadd(rkey, {str(now): now})
        pipe.expire(rkey, int(window) + 1)
        results = await pipe.execute()
        count = results[1]
        headers = {
            "X-RateLimit-Limit": str(self._rpm),
            "X-RateLimit-Remaining": str(max(0, self._rpm - count - 1)),
        }
        if count >= self._rpm:
            headers["Retry-After"] = "1"
            return False, headers
        return True, headers


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, limiter: TokenBucket | RedisTokenBucket) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        key = request.headers.get("x-api-key", "") or request.client.host if request.client else "unknown"

        if isinstance(self._limiter, RedisTokenBucket):
            allowed, headers = await self._limiter.allow(key)
        else:
            allowed, headers = self._limiter.allow(key)

        if not allowed:
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers=headers,
            )

        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response


def setup_rate_limiter(
    app: FastAPI,
    rpm: int = 600,
    burst: int = 60,
    redis_url: str = "",
) -> None:
    if redis_url:
        limiter = RedisTokenBucket(redis_url, rpm, burst)
    else:
        rate_per_sec = rpm / 60.0
        limiter = TokenBucket(rate_per_sec, burst)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
