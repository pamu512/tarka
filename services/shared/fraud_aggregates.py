from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
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
_FEATURE_KINDS = frozenset({"event_count", "sum", "avg", "distinct"})
# ponytail: fallback if the bundled manifest is missing or all rows skip; upgrade is ship the JSON with this module
DEFAULT_FEATURE_OUTPUTS: list[dict] = [
    {"name": "event_count_5m", "kind": "event_count", "window_seconds": 300},
    {"name": "event_count_1h", "kind": "event_count", "window_seconds": 3600},
    {"name": "event_count_24h", "kind": "event_count", "window_seconds": 86400},
    {"name": "event_count_7d", "kind": "event_count", "window_seconds": 604800},
    {"name": "sum_amount_1h", "kind": "sum", "field": "amount", "window_seconds": 3600},
    {"name": "avg_amount_1h", "kind": "avg", "field": "amount", "window_seconds": 3600},
    {"name": "sum_amount_24h", "kind": "sum", "field": "amount", "window_seconds": 86400},
    {"name": "avg_amount_24h", "kind": "avg", "field": "amount", "window_seconds": 86400},
    {"name": "distinct_ip_address_24h", "kind": "distinct", "field": "ip_address", "window_seconds": 86400},
    {"name": "distinct_device_id_24h", "kind": "distinct", "field": "device_id", "window_seconds": 86400},
    {"name": "distinct_session_id_24h", "kind": "distinct", "field": "session_id", "window_seconds": 86400},
]


def valid_feature_output_rows(raw: list | None) -> list[dict]:
    """Keep rows with name, known kind, and window_seconds in (0, MAX_WINDOW]."""
    kept: list[dict] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        kind = row.get("kind")
        try:
            window = int(row.get("window_seconds", 0))
        except (TypeError, ValueError):
            continue
        if name and kind in _FEATURE_KINDS and 0 < window <= MAX_WINDOW:
            kept.append(row)
    return kept


@lru_cache
def _bundled_manifest_feature_outputs() -> tuple[dict, ...] | None:
    path = (
        Path(__file__).resolve().parent.parent
        / "decision-api"
        / "src"
        / "decision_api"
        / "data"
        / "counter_manifest_v1.json"
    )
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8")).get("feature_outputs")
    if not isinstance(raw, list):
        return None
    return tuple(row for row in raw if isinstance(row, dict))


def _rows_for_compute(feature_outputs: list[dict] | None) -> list[dict]:
    raw: list | None = feature_outputs
    if raw is None:
        bundled = _bundled_manifest_feature_outputs()
        raw = list(bundled) if bundled is not None else None
    return valid_feature_output_rows(raw) or list(DEFAULT_FEATURE_OUTPUTS)


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
        feature_outputs: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Compute aggregate features from validated manifest rows."""
        features: dict[str, Any] = {}
        for row in _rows_for_compute(feature_outputs):
            name = str(row["name"]).strip()
            kind = row["kind"]
            window = int(row["window_seconds"])
            if kind == "event_count":
                features[name] = await self.count(tenant_id, entity_id, window)
                continue
            field = row.get("field")
            if kind in ("sum", "avg"):
                if field is None or field not in fields:
                    continue
                if kind == "sum":
                    features[name] = await self.sum_field(
                        tenant_id, entity_id, field, window
                    )
                else:
                    features[name] = await self.avg_field(
                        tenant_id, entity_id, field, window
                    )
                continue
            if kind == "distinct" and field and fields.get(field):
                features[name] = await self.distinct_count(
                    tenant_id, entity_id, field, window
                )
        return features


def normalized_velocity_key_names() -> tuple[str, ...]:
    """Manifest names in file order (valid rows only)."""
    return tuple(str(row["name"]).strip() for row in _rows_for_compute(None))
