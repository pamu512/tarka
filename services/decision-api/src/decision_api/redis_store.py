import json
import os
from typing import Any

import redis.asyncio as redis

from decision_api.config import settings

TAG_PREFIX = "fraud:tags:"
SCORE_PREFIX = "fraud:score:"
NONCE_PREFIX = "fraud:nonce:"
TTL_SECONDS = 86400 * 7

SCORE_TTL_SECONDS = int(os.environ.get("REDIS_SCORE_TTL_SECONDS", str(86400 * 7)))
TAGS_TTL_SECONDS = int(os.environ.get("REDIS_TAGS_TTL_SECONDS", str(86400 * 90)))

MERGE_TAGS_LUA = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local existing = redis.call('GET', key)
local set = {}
if existing then
    local decoded = cjson.decode(existing)
    for _, v in ipairs(decoded) do set[v] = true end
end
for i = 2, #ARGV do
    set[ARGV[i]] = true
end
local result = {}
for k in pairs(set) do result[#result + 1] = k end
table.sort(result)
redis.call('SETEX', key, ttl, cjson.encode(result))
return cjson.encode(result)
"""


class RedisTags:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None
        self._merge_sha: str | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
            self._merge_sha = await self._client.script_load(MERGE_TAGS_LUA)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _key_tags(self, tenant_id: str, entity_id: str) -> str:
        return f"{TAG_PREFIX}{tenant_id}:{entity_id}"

    def _key_score(self, tenant_id: str, entity_id: str) -> str:
        return f"{SCORE_PREFIX}{tenant_id}:{entity_id}"

    async def get_tags(self, tenant_id: str, entity_id: str) -> list[str]:
        await self.connect()
        assert self._client
        raw = await self._client.get(self._key_tags(tenant_id, entity_id))
        if not raw:
            return []
        data = json.loads(raw)
        return list(data) if isinstance(data, list) else []

    async def set_tags(self, tenant_id: str, entity_id: str, tags: list[str]) -> None:
        await self.connect()
        assert self._client
        key = self._key_tags(tenant_id, entity_id)
        await self._client.setex(key, TAGS_TTL_SECONDS, json.dumps(sorted(tags)))

    async def merge_tags(self, tenant_id: str, entity_id: str, new_tags: list[str]) -> list[str]:
        """Atomically merge new_tags into existing using server-side Lua."""
        if not new_tags:
            return await self.get_tags(tenant_id, entity_id)
        await self.connect()
        assert self._client and self._merge_sha
        key = self._key_tags(tenant_id, entity_id)
        result = await self._client.evalsha(
            self._merge_sha, 1, key, str(TAGS_TTL_SECONDS), *new_tags
        )
        return json.loads(result) if result else sorted(new_tags)

    async def get_cached_score(self, tenant_id: str, entity_id: str) -> float | None:
        await self.connect()
        assert self._client
        raw = await self._client.get(self._key_score(tenant_id, entity_id))
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    async def set_cached_score(self, tenant_id: str, entity_id: str, score: float) -> None:
        await self.connect()
        assert self._client
        await self._client.setex(self._key_score(tenant_id, entity_id), SCORE_TTL_SECONDS, str(score))

    # --- Attestation nonces ---

    async def store_nonce(self, nonce: str, ttl: int) -> None:
        await self.connect()
        assert self._client
        await self._client.setex(f"{NONCE_PREFIX}{nonce}", ttl, "1")

    async def consume_nonce(self, nonce: str) -> bool:
        """Atomically consume nonce — getdel ensures no double-use."""
        await self.connect()
        assert self._client
        key = f"{NONCE_PREFIX}{nonce}"
        val = await self._client.getdel(key)
        return val is not None


redis_tags = RedisTags(settings.redis_url)
