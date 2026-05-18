from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis

"""Real-time aggregate computation using Redis sorted sets.

Shared by decision-api (writes) and feature-service (reads) so velocity keys stay aligned.

Each event is recorded in Redis sorted sets keyed by (tenant, entity, metric).
The score is the Unix timestamp, the member is a unique event ID or value.
Aggregates are computed on-the-fly over sliding time windows.

Supported aggregate types:
  - count(entity, window)    — number of events in window
  - sum(entity, field, window) — sum of a numeric field in window
  - avg(entity, field, window) — average of a numeric field in window
  - distinct(entity, field, window) — count of distinct values in window
"""
AGG_PREFIX = "fraud:agg:"
AGG_VAL_PREFIX = "fraud:aggval:"
MAX_WINDOW = 86400 * 30  # 30 days max


def _agg_key_version_segment() -> str:
    """Optional Redis key segment for migrations (set AGG_KEY_VERSION). Empty = legacy keys."""
    raw = os.environ.get("AGG_KEY_VERSION", "").strip()
    if not raw or not all(c.isalnum() or c in "._:-" for c in raw):
        return ""
    return raw + ":"


NUMERIC_FIELDS = frozenset({"amount", "score", "price", "quantity", "original_amount"})
DISTINCT_FIELDS = frozenset(
    {
        "ip_address",
        "device_id",
        "session_id",
        "email",
        "phone",
        "card_hash",
        "country",
        "original_currency",
    }
)


class AggregateStore:
    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._client = redis_client
        self._clock: Callable[[], float] = clock or time.time

    def set_client(self, client: redis.Redis) -> None:
        self._client = client

    def _key(self, tenant_id: str, entity_id: str, metric: str) -> str:
        vs = _agg_key_version_segment()
        return f"{AGG_PREFIX}{vs}{tenant_id}:{entity_id}:{metric}"

    def _val_key(self, tenant_id: str, entity_id: str, metric: str) -> str:
        vs = _agg_key_version_segment()
        return f"{AGG_VAL_PREFIX}{vs}{tenant_id}:{entity_id}:{metric}"

    async def record_event(
        self,
        tenant_id: str,
        entity_id: str,
        event_id: str,
        fields: dict[str, Any],
        ts: float | None = None,
    ) -> None:
        assert self._client
        now = self._clock() if ts is None else ts
        pipe = self._client.pipeline()

        # Always record in the "events" sorted set for count
        events_key = self._key(tenant_id, entity_id, "events")
        pipe.zadd(events_key, {event_id: now})
        pipe.expire(events_key, MAX_WINDOW + 3600)

        for field, value in fields.items():
            if field in NUMERIC_FIELDS and isinstance(value, (int, float)):
                fkey = self._key(tenant_id, entity_id, f"field:{field}")
                pipe.zadd(fkey, {f"{event_id}:{value}": now})
                pipe.expire(fkey, MAX_WINDOW + 3600)

            if field in DISTINCT_FIELDS and value is not None:
                dkey = self._key(tenant_id, entity_id, f"distinct:{field}")
                pipe.zadd(dkey, {str(value): now})
                pipe.expire(dkey, MAX_WINDOW + 3600)

        await pipe.execute()

    async def count(self, tenant_id: str, entity_id: str, window_seconds: int) -> int:
        assert self._client
        key = self._key(tenant_id, entity_id, "events")
        cutoff = self._clock() - min(window_seconds, MAX_WINDOW)
        return await self._client.zcount(key, cutoff, "+inf")

    async def sum_field(
        self, tenant_id: str, entity_id: str, field: str, window_seconds: int
    ) -> float:
        assert self._client
        key = self._key(tenant_id, entity_id, f"field:{field}")
        cutoff = self._clock() - min(window_seconds, MAX_WINDOW)
        members = await self._client.zrangebyscore(key, cutoff, "+inf")
        total = 0.0
        for m in members:
            try:
                parts = str(m).rsplit(":", 1)
                total += float(parts[-1])
            except (ValueError, IndexError):
                continue
        return total

    async def avg_field(
        self, tenant_id: str, entity_id: str, field: str, window_seconds: int
    ) -> float | None:
        assert self._client
        key = self._key(tenant_id, entity_id, f"field:{field}")
        cutoff = self._clock() - min(window_seconds, MAX_WINDOW)
        members = await self._client.zrangebyscore(key, cutoff, "+inf")
        if not members:
            return None
        total = 0.0
        count = 0
        for m in members:
            try:
                parts = str(m).rsplit(":", 1)
                total += float(parts[-1])
                count += 1
            except (ValueError, IndexError):
                continue
        return total / count if count else None

    async def distinct_count(
        self, tenant_id: str, entity_id: str, field: str, window_seconds: int
    ) -> int:
        assert self._client
        key = self._key(tenant_id, entity_id, f"distinct:{field}")
        cutoff = self._clock() - min(window_seconds, MAX_WINDOW)
        return await self._client.zcount(key, cutoff, "+inf")

    async def compute_features(
        self,
        tenant_id: str,
        entity_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute standard aggregate features and return them as a dict."""
        features: dict[str, Any] = {}
        for window_label, window_secs in [
            ("5m", 300),
            ("1h", 3600),
            ("24h", 86400),
            ("7d", 604800),
        ]:
            features[f"event_count_{window_label}"] = await self.count(
                tenant_id, entity_id, window_secs
            )

        for field in ("amount",):
            if field in fields:
                for window_label, window_secs in [("1h", 3600), ("24h", 86400)]:
                    features[f"sum_{field}_{window_label}"] = await self.sum_field(
                        tenant_id, entity_id, field, window_secs
                    )
                    features[f"avg_{field}_{window_label}"] = await self.avg_field(
                        tenant_id, entity_id, field, window_secs
                    )

        for field in ("ip_address", "device_id", "session_id"):
            if fields.get(field):
                features[f"distinct_{field}_24h"] = await self.distinct_count(
                    tenant_id, entity_id, field, 86400
                )

        return features


def normalized_velocity_key_names() -> tuple[str, ...]:
    """Stable ordering for rule authors / docs (matches compute_features when all branches apply)."""
    return (
        "event_count_5m",
        "event_count_1h",
        "event_count_24h",
        "event_count_7d",
        "sum_amount_1h",
        "avg_amount_1h",
        "sum_amount_24h",
        "avg_amount_24h",
        "distinct_ip_address_24h",
        "distinct_device_id_24h",
        "distinct_session_id_24h",
    )
