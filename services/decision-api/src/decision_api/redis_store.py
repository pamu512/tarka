import json
import os
from typing import Any

import redis.asyncio as redis

from decision_api.config import settings

TAG_PREFIX = "fraud:tags:"
SCORE_PREFIX = "fraud:score:"
NONCE_PREFIX = "fraud:nonce:"
CONSORTIUM_PREFIX = "fraud:consortium:"
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

    # --- Consortium intelligence ---

    def _key_consortium(self, consortium_id: str, signal_hash: str) -> str:
        return f"{CONSORTIUM_PREFIX}{consortium_id}:{signal_hash}"

    def _key_consortium_tenant_trust(self, consortium_id: str) -> str:
        return f"{CONSORTIUM_PREFIX}{consortium_id}:tenant_trust"

    async def set_consortium_tenant_trust(
        self,
        consortium_id: str,
        tenant_id: str,
        trust_score: float,
    ) -> dict[str, Any]:
        await self.connect()
        assert self._client
        key = self._key_consortium_tenant_trust(consortium_id)
        score = max(0.1, min(2.0, float(trust_score)))
        await self._client.hset(key, tenant_id, str(score))
        return {"consortium_id": consortium_id, "tenant_id": tenant_id, "trust_score": score}

    async def get_consortium_tenant_trust(self, consortium_id: str, tenant_id: str) -> float:
        await self.connect()
        assert self._client
        key = self._key_consortium_tenant_trust(consortium_id)
        raw = await self._client.hget(key, tenant_id)
        if raw is None:
            return 1.0
        try:
            return max(0.1, min(2.0, float(raw)))
        except ValueError:
            return 1.0

    async def record_consortium_signal(
        self,
        consortium_id: str,
        signal_hash: str,
        signal_type: str,
        reporter_tenant: str,
        severity: float,
        ttl_days: int = 30,
    ) -> dict[str, Any]:
        await self.connect()
        assert self._client
        key = self._key_consortium(consortium_id, signal_hash)
        raw = await self._client.get(key)
        current: dict[str, Any] = json.loads(raw) if raw else {}
        tenants = set(current.get("tenants", []))
        tenants.add(reporter_tenant)
        signal_counts = dict(current.get("signal_counts", {}))
        signal_counts[signal_type] = int(signal_counts.get(signal_type, 0)) + 1
        report_count = int(current.get("report_count", 0)) + 1
        max_severity = max(float(current.get("max_severity", 0.0)), float(severity))
        trust_map = dict(current.get("tenant_trust", {}))
        if reporter_tenant not in trust_map:
            trust_map[reporter_tenant] = await self.get_consortium_tenant_trust(consortium_id, reporter_tenant)
        weighted_tenant_score = sum(float(v) for v in trust_map.values())
        weighted_report_score = float(current.get("weighted_report_score", 0.0)) + float(trust_map[reporter_tenant])
        false_positive_count = int(current.get("false_positive_count", 0))
        confirmed_fraud_count = int(current.get("confirmed_fraud_count", 0))
        denom = max(1, false_positive_count + confirmed_fraud_count)
        false_positive_rate = false_positive_count / denom
        # quality score: trust-weighted coverage penalized by false positive rate.
        coverage = min(1.0, len(tenants) / 10.0)
        trust_norm = min(1.5, weighted_tenant_score / max(1.0, len(tenants)))
        quality_score = max(0.2, (coverage * trust_norm) * max(0.2, 1.0 - false_positive_rate))
        updated = {
            "consortium_id": consortium_id,
            "tenant_count": len(tenants),
            "tenants": sorted(tenants),
            "tenant_trust": trust_map,
            "signal_counts": signal_counts,
            "report_count": report_count,
            "max_severity": max_severity,
            "weighted_tenant_score": weighted_tenant_score,
            "weighted_report_score": weighted_report_score,
            "false_positive_count": false_positive_count,
            "confirmed_fraud_count": confirmed_fraud_count,
            "false_positive_rate": false_positive_rate,
            "quality_score": quality_score,
        }
        ttl = max(1, int(ttl_days)) * 86400
        await self._client.setex(key, ttl, json.dumps(updated))
        return updated

    async def check_consortium_signal(self, consortium_id: str, signal_hash: str) -> dict[str, Any]:
        await self.connect()
        assert self._client
        raw = await self._client.get(self._key_consortium(consortium_id, signal_hash))
        if not raw:
            return {
                "consortium_id": consortium_id,
                "tenant_count": 0,
                "signal_counts": {},
                "report_count": 0,
                "max_severity": 0.0,
            }
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {
                "consortium_id": consortium_id,
                "tenant_count": 0,
                "signal_counts": {},
                "report_count": 0,
                "max_severity": 0.0,
            }
        data.pop("tenants", None)
        data.pop("tenant_trust", None)
        return data

    async def add_consortium_feedback(
        self,
        consortium_id: str,
        signal_hash: str,
        outcome: str,
        ttl_days: int = 30,
    ) -> dict[str, Any]:
        await self.connect()
        assert self._client
        key = self._key_consortium(consortium_id, signal_hash)
        raw = await self._client.get(key)
        current: dict[str, Any] = json.loads(raw) if raw else {}
        fp = int(current.get("false_positive_count", 0))
        cf = int(current.get("confirmed_fraud_count", 0))
        if outcome == "false_positive":
            fp += 1
        elif outcome == "confirmed_fraud":
            cf += 1
        current["false_positive_count"] = fp
        current["confirmed_fraud_count"] = cf
        denom = max(1, fp + cf)
        current["false_positive_rate"] = fp / denom
        ttl = max(1, int(ttl_days)) * 86400
        await self._client.setex(key, ttl, json.dumps(current))
        current.pop("tenants", None)
        current.pop("tenant_trust", None)
        return current


redis_tags = RedisTags(settings.redis_url)
