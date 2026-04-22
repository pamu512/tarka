from __future__ import annotations

"""Server-side entity ↔ device ↔ vendor ID linking (Redis).

Keys (tenant-scoped, TTL aligned with fingerprint store where applicable):
  fraud:link:device_entity:{tenant}:{device_id}  -> ZSET member=entity_id, score=last_seen unix
  fraud:link:vendor:{tenant}:{vendor_type}:{vendor_id} -> SET value=entity_id (last write wins)

Metadata keys on evaluate (optional):
  vendor_device_id   — e.g. vendor visitor / device id string
  vendor_install_id  — e.g. analytics install id
  vendor_visitor_id  — alias for cross-session visitor (same as vendor_device_id if only one)
"""


import time
from typing import Any

import redis.asyncio as aioredis

LINK_DEVICE_ENTITY_PREFIX = "fraud:link:device_entity:"
LINK_VENDOR_PREFIX = "fraud:link:vendor:"
LINK_TTL = 86400 * 90  # 90 days, matches fingerprint TTL spirit


def _require_client(client: aioredis.Redis | None) -> aioredis.Redis:
    if client is None:
        raise RuntimeError("EntityLinkStore Redis client not initialized")
    return client


class EntityLinkStore:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    def set_client(self, client: aioredis.Redis) -> None:
        self._client = client

    def _device_entity_key(self, tenant_id: str, device_id: str) -> str:
        return f"{LINK_DEVICE_ENTITY_PREFIX}{tenant_id}:{device_id}"

    def _vendor_key(self, tenant_id: str, vendor_type: str, vendor_id: str) -> str:
        return f"{LINK_VENDOR_PREFIX}{tenant_id}:{vendor_type}:{vendor_id}"

    async def record_device_entity_link(self, tenant_id: str, device_id: str, entity_id: str) -> None:
        client = _require_client(self._client)
        now = time.time()
        key = self._device_entity_key(tenant_id, device_id)
        pipe = client.pipeline()
        pipe.zadd(key, {entity_id: now})
        pipe.expire(key, LINK_TTL)
        await pipe.execute()

    async def record_vendor_bridge(
        self,
        tenant_id: str,
        entity_id: str,
        metadata: dict[str, Any],
    ) -> None:
        """Map optional vendor_* ids in metadata to entity_id."""
        client = _require_client(self._client)
        pairs: list[tuple[str, str]] = []
        for k, v in metadata.items():
            if not isinstance(v, str) or not v.strip():
                continue
            if k == "vendor_device_id":
                pairs.append(("device", v.strip()))
            elif k == "vendor_install_id":
                pairs.append(("install", v.strip()))
            elif k == "vendor_visitor_id":
                pairs.append(("visitor", v.strip()))
        if not pairs:
            return
        pipe = client.pipeline()
        for vtype, vid in pairs:
            vk = self._vendor_key(tenant_id, vtype, vid)
            pipe.setex(vk, LINK_TTL, entity_id)
        await pipe.execute()

    async def get_entities_for_device(self, tenant_id: str, device_id: str, limit: int = 50) -> list[str]:
        client = _require_client(self._client)
        key = self._device_entity_key(tenant_id, device_id)
        # Most recent first
        raw = await client.zrevrange(key, 0, max(0, limit - 1))
        return [str(x) for x in raw]

    async def get_entity_for_vendor(self, tenant_id: str, vendor_type: str, vendor_id: str) -> str | None:
        client = _require_client(self._client)
        vk = self._vendor_key(tenant_id, vendor_type, vendor_id)
        val = await client.get(vk)
        return str(val) if val else None


entity_link_store = EntityLinkStore()
