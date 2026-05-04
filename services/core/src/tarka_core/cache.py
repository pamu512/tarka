"""Pluggable async key-value cache (Redis production, in-process dict for Tarka Micro)."""

from __future__ import annotations

import asyncio
import copy
import time
from abc import ABC, abstractmethod


class KeyValueCache(ABC):
    """Minimal string cache surface (Redis-compatible values as UTF-8 text)."""

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Return a **deep-copied** logical value (caller may mutate a parsed structure safely)."""

    @abstractmethod
    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        """Persist ``value``; store a **deep copy** so later mutations of caller buffers do not alias cache state."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove key if present."""

    async def aclose(self) -> None:
        """Release network resources (no-op for in-process caches)."""


class LocalDictCache(KeyValueCache):
    """Process-local TTL cache with deep copies on read/write to mimic serialization boundaries."""

    __slots__ = ("_data", "_lock")

    def __init__(self) -> None:
        self._data: dict[str, tuple[float | None, str]] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return time.monotonic()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            row = self._data.get(key)
            if not row:
                return None
            exp, val = row
            if exp is not None and self._now() >= exp:
                del self._data[key]
                return None
            return copy.deepcopy(val)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        stored = copy.deepcopy(value)
        exp: float | None = None
        if ttl_seconds is not None:
            ttl = int(ttl_seconds)
            if ttl > 0:
                exp = self._now() + float(ttl)
        async with self._lock:
            self._data[key] = (exp, stored)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def aclose(self) -> None:
        async with self._lock:
            self._data.clear()


class RedisCache(KeyValueCache):
    """Thin ``redis.asyncio`` wrapper implementing :class:`KeyValueCache` with deep-copy semantics on values."""

    __slots__ = ("_url", "_client")

    def __init__(self, url: str) -> None:
        self._url = (url or "").strip()
        self._client = None

    async def connect(self) -> None:
        if self._client is not None or not self._url:
            return
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(self._url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        if not self._client:
            return None
        raw = await self._client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8", errors="replace")
        return copy.deepcopy(str(raw))

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        if not self._client:
            return
        stored = copy.deepcopy(value)
        if ttl_seconds is not None and int(ttl_seconds) > 0:
            await self._client.setex(key, int(ttl_seconds), stored)
        else:
            await self._client.set(key, stored)

    async def delete(self, key: str) -> None:
        if self._client:
            await self._client.delete(key)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
