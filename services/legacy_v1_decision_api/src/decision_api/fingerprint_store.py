from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis

"""Redis-backed browser fingerprint store.

Tracks device fingerprints across entities and time, enabling cross-entity
shared-device detection.

Key schema (all tenant-scoped):
    fraud:fp:{tenant}:{fp_hash}          -> JSON FingerprintRecord
    fraud:fp:entity:{tenant}:{entity_id} -> sorted set of fp_hashes (score=last_seen)
"""
FP_PREFIX = "fraud:fp:"
FP_ENTITY_PREFIX = "fraud:fp:entity:"
FP_TTL = 86400 * 90  # 90 days

_RECORD_LUA = """
local key   = KEYS[1]
local ekey  = KEYS[2]
local eid   = ARGV[1]
local now   = tonumber(ARGV[2])
local ttl   = tonumber(ARGV[3])
local fph   = ARGV[4]

local raw = redis.call('GET', key)
local rec
if raw then
    rec = cjson.decode(raw)
    rec['last_seen'] = now
    rec['event_count'] = rec['event_count'] + 1
    local found = false
    for _, v in ipairs(rec['entity_ids']) do
        if v == eid then found = true; break end
    end
    if not found then
        table.insert(rec['entity_ids'], eid)
    end
else
    rec = {
        fp_hash = fph,
        first_seen = now,
        last_seen = now,
        entity_ids = {eid},
        event_count = 1
    }
end

redis.call('SETEX', key, ttl, cjson.encode(rec))
redis.call('ZADD', ekey, now, fph)
redis.call('EXPIRE', ekey, ttl)
return cjson.encode(rec)
"""


@dataclass
class FingerprintRecord:
    fp_hash: str
    first_seen: float
    last_seen: float
    entity_ids: set[str] = field(default_factory=set)
    event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fp_hash": self.fp_hash,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "entity_ids": sorted(self.entity_ids),
            "event_count": self.event_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FingerprintRecord:
        return cls(
            fp_hash=d["fp_hash"],
            first_seen=d["first_seen"],
            last_seen=d["last_seen"],
            entity_ids=set(d.get("entity_ids", [])),
            event_count=d.get("event_count", 0),
        )


def compute_fp_hash(device_context: dict[str, Any]) -> str:
    """Deterministic SHA-256 of fingerprint-relevant device components."""
    parts = [
        str(device_context.get("device_id", "")),
        str(device_context.get("platform", "")),
    ]
    signals = device_context.get("signals", {})
    for key in sorted(signals.keys()):
        v = signals[key]
        if isinstance(v, (str, int, float, bool)):
            parts.append(f"{key}={v}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_client(client: aioredis.Redis | None) -> aioredis.Redis:
    if client is None:
        raise RuntimeError("FingerprintStore Redis client not initialized")
    return client


class FingerprintStore:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._record_script: Any = None

    def set_client(self, client: aioredis.Redis) -> None:
        self._client = client
        self._record_script = client.register_script(_RECORD_LUA)

    def _fp_key(self, tenant_id: str, fp_hash: str) -> str:
        return f"{FP_PREFIX}{tenant_id}:{fp_hash}"

    def _entity_key(self, tenant_id: str, entity_id: str) -> str:
        return f"{FP_ENTITY_PREFIX}{tenant_id}:{entity_id}"

    async def record_fingerprint(
        self,
        tenant_id: str,
        device_context: dict[str, Any],
        entity_id: str,
    ) -> FingerprintRecord:
        """Atomically record a fingerprint observation via Lua script."""
        client = _require_client(self._client)
        fp_hash = compute_fp_hash(device_context)
        now = time.time()
        key = self._fp_key(tenant_id, fp_hash)
        ekey = self._entity_key(tenant_id, entity_id)

        if self._record_script is not None:
            raw = await self._record_script(
                keys=[key, ekey],
                args=[entity_id, str(now), str(FP_TTL), fp_hash],
            )
            return FingerprintRecord.from_dict(json.loads(raw))

        # Fallback without script (should not normally reach here)
        pipe = client.pipeline(transaction=True)
        pipe.get(key)
        results = await pipe.execute()
        existing = results[0]

        if existing:
            record = FingerprintRecord.from_dict(json.loads(existing))
            record.last_seen = now
            record.entity_ids.add(entity_id)
            record.event_count += 1
        else:
            record = FingerprintRecord(
                fp_hash=fp_hash,
                first_seen=now,
                last_seen=now,
                entity_ids={entity_id},
                event_count=1,
            )

        pipe2 = client.pipeline(transaction=True)
        pipe2.setex(key, FP_TTL, json.dumps(record.to_dict()))
        pipe2.zadd(ekey, {fp_hash: now})
        pipe2.expire(ekey, FP_TTL)
        await pipe2.execute()
        return record

    async def get_fingerprint(
        self, tenant_id: str, fp_hash: str
    ) -> FingerprintRecord | None:
        client = _require_client(self._client)
        raw = await client.get(self._fp_key(tenant_id, fp_hash))
        if not raw:
            return None
        return FingerprintRecord.from_dict(json.loads(raw))

    async def get_entity_fingerprints(
        self, tenant_id: str, entity_id: str
    ) -> list[FingerprintRecord]:
        client = _require_client(self._client)
        entity_key = self._entity_key(tenant_id, entity_id)
        fp_hashes = await client.zrange(entity_key, 0, -1)
        records: list[FingerprintRecord] = []
        for h in fp_hashes:
            r = await self.get_fingerprint(tenant_id, str(h))
            if r:
                records.append(r)
        return records


fingerprint_store = FingerprintStore()
