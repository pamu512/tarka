import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from decision_api.config import settings
from tarka_core.cache import KeyValueCache
from tarka_core.internal_monitor import InternalMonitor

log = logging.getLogger(__name__)

TAG_PREFIX = "fraud:tags:"
SCORE_PREFIX = "fraud:score:"
NONCE_PREFIX = "fraud:nonce:"
CONSORTIUM_PREFIX = "fraud:consortium:"
REPLAY_PREFIX = "fraud:replay:"
TENANT_FLAGS_PREFIX = "fraud:tenant_flags:"
TTL_SECONDS = 86400 * 7

SCORE_TTL_SECONDS = int(os.environ.get("REDIS_SCORE_TTL_SECONDS", str(86400 * 7)))
TAGS_TTL_SECONDS = int(os.environ.get("REDIS_TAGS_TTL_SECONDS", str(86400 * 90)))


def _redis_merge_timeout_s() -> float:
    """When > 0, Redis Lua merge_tags is bounded by asyncio.wait_for; slow/partitioned Redis can fail over to KV."""
    return float(os.environ.get("REDIS_MERGE_TIMEOUT_SECONDS", "0") or 0)


def _fallback_lock_file_path() -> Path:
    raw = (os.environ.get("TARKA_KV_FALLBACK_LOCK_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "data" / "tarka_kv_fallback.lock").resolve()


def _acquire_kv_fallback_lock(lock_path: Path):
    """Open ``lock_path`` and take an exclusive OS-level lock (multi-worker / multi-process safe)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lf = open(lock_path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            lf.seek(0)
            try:
                msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    except Exception:
        lf.close()
        raise
    return lf


def _release_kv_fallback_lock(lf: Any) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    finally:
        lf.close()


async def _kv_fallback_lock_acquire(lock_path: Path) -> Any:
    return await asyncio.to_thread(_acquire_kv_fallback_lock, lock_path)


async def _kv_fallback_lock_release(lf: Any) -> None:
    await asyncio.to_thread(_release_kv_fallback_lock, lf)


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


def _consortium_metrics_recompute(current: dict[str, Any]) -> dict[str, Any]:
    """Normalize and recompute consortium quality metrics for share + feedback paths."""
    tenants = sorted(
        {str(x).strip() for x in (current.get("tenants") or []) if str(x).strip()}
    )
    trust_map_raw = current.get("tenant_trust")
    trust_map: dict[str, float] = {}
    if isinstance(trust_map_raw, dict):
        for tenant_id, trust_value in trust_map_raw.items():
            t = str(tenant_id).strip()
            if not t:
                continue
            try:
                trust_map[t] = max(0.1, min(2.0, float(trust_value)))
            except (TypeError, ValueError):
                trust_map[t] = 1.0
    for tenant_id in tenants:
        trust_map.setdefault(tenant_id, 1.0)

    signal_counts_raw = current.get("signal_counts")
    signal_counts: dict[str, int] = {}
    if isinstance(signal_counts_raw, dict):
        for signal_type, count in signal_counts_raw.items():
            key = str(signal_type).strip().lower()
            if not key:
                continue
            try:
                signal_counts[key] = max(0, int(count))
            except (TypeError, ValueError):
                signal_counts[key] = 0

    report_count_default = sum(signal_counts.values())
    report_count = max(
        0,
        int(current.get("report_count", report_count_default) or report_count_default),
    )
    if report_count == 0 and report_count_default > 0:
        report_count = report_count_default

    try:
        max_severity = max(
            0.0, min(5.0, float(current.get("max_severity", 0.0) or 0.0))
        )
    except (TypeError, ValueError):
        max_severity = 0.0

    try:
        weighted_report_score = float(current.get("weighted_report_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        weighted_report_score = 0.0
    if weighted_report_score <= 0.0 and report_count > 0:
        avg_trust = sum(trust_map.values()) / max(1, len(trust_map))
        weighted_report_score = float(report_count) * avg_trust

    weighted_tenant_score = (
        sum(float(v) for v in trust_map.values()) if trust_map else 0.0
    )
    false_positive_count = max(0, int(current.get("false_positive_count", 0) or 0))
    confirmed_fraud_count = max(0, int(current.get("confirmed_fraud_count", 0) or 0))
    denom = max(1, false_positive_count + confirmed_fraud_count)
    false_positive_rate = false_positive_count / denom
    coverage = min(1.0, len(tenants) / 10.0)
    trust_norm = min(1.5, weighted_tenant_score / max(1.0, len(tenants)))
    quality_score = max(
        0.2, (coverage * trust_norm) * max(0.2, 1.0 - false_positive_rate)
    )

    current.update(
        {
            "tenant_count": len(tenants),
            "tenants": tenants,
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
    )
    return current


class RedisTags:
    """Redis-backed tags (production) or :class:`tarka_core.cache.KeyValueCache` when ``REDIS_URL`` is empty (Micro)."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None
        self._merge_sha: str | None = None
        self._kv: KeyValueCache | None = None
        self._kv_degraded: KeyValueCache | None = None
        self._async_lock = asyncio.Lock()
        self._fallback_lock_path = _fallback_lock_file_path()

    @property
    def has_remote_redis(self) -> bool:
        return self._client is not None

    @property
    def has_kv_backing(self) -> bool:
        return self._kv is not None

    @property
    def is_tag_store_available(self) -> bool:
        """True when tags, scores, nonces, tenant flags, or consortium keys can be persisted."""
        return self._client is not None or self._kv is not None

    async def connect(self, *, kv_fallback: KeyValueCache | None = None) -> None:
        if kv_fallback is not None:
            self._kv_degraded = kv_fallback
        if self._client is not None or self._kv is not None:
            return
        url = (self._url or "").strip()
        if url:
            self._client = redis.from_url(url, decode_responses=True)
            self._merge_sha = await self._client.script_load(MERGE_TAGS_LUA)
            return
        if kv_fallback is not None:
            self._kv = kv_fallback

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._merge_sha = None
        self._kv = None
        self._kv_degraded = None

    def _key_tags(self, tenant_id: str, entity_id: str) -> str:
        return f"{TAG_PREFIX}{tenant_id}:{entity_id}"

    def _key_score(self, tenant_id: str, entity_id: str) -> str:
        return f"{SCORE_PREFIX}{tenant_id}:{entity_id}"

    async def get_tags(self, tenant_id: str, entity_id: str) -> list[str]:
        await self.connect()
        key = self._key_tags(tenant_id, entity_id)
        if self._client:
            raw = await self._client.get(key)
        elif self._kv:
            raw = await self._kv.get(key)
        else:
            return []
        if not raw:
            return []
        data = json.loads(raw)
        return list(data) if isinstance(data, list) else []

    async def set_tags(self, tenant_id: str, entity_id: str, tags: list[str]) -> None:
        await self.connect()
        key = self._key_tags(tenant_id, entity_id)
        blob = json.dumps(sorted(tags))
        if self._client:
            await self._client.setex(key, TAGS_TTL_SECONDS, blob)
        elif self._kv:
            await self._kv.set(key, blob, ttl_seconds=TAGS_TTL_SECONDS)

    async def _redis_merge_failover_to_kv_reserve(self) -> None:
        """After merge deadline exceeded: drop Redis client so reads/writes use the reserved local KV store."""
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                log.exception("redis_close_during_kv_failover")
        self._client = None
        self._merge_sha = None
        if self._kv_degraded is not None:
            self._kv = self._kv_degraded

    async def _merge_tags_via_kv_store(
        self, kv: KeyValueCache, key: str, new_tags: list[str]
    ) -> list[str]:
        lock_handle = await _kv_fallback_lock_acquire(self._fallback_lock_path)
        try:
            raw = await kv.get(key)
            cur: set[str] = set()
            if raw:
                try:
                    data = json.loads(raw)
                    if isinstance(data, list):
                        cur.update(str(x) for x in data)
                except json.JSONDecodeError as exc:
                    InternalMonitor.log_suppressed_error(
                        exc,
                        context="merge_tags_kv_corrupt_json",
                        domain="redis_tags",
                        level=logging.DEBUG,
                        key=key,
                    )
            cur.update(str(x) for x in new_tags)
            merged_sorted = sorted(cur)
            await kv.set(key, json.dumps(merged_sorted), ttl_seconds=TAGS_TTL_SECONDS)
            return merged_sorted
        finally:
            await _kv_fallback_lock_release(lock_handle)

    async def merge_tags(
        self, tenant_id: str, entity_id: str, new_tags: list[str]
    ) -> list[str]:
        """Atomically merge new_tags into existing using server-side Lua (Redis) or locked read-modify-write (Micro)."""
        await self.connect()
        key = self._key_tags(tenant_id, entity_id)
        if not new_tags:
            return await self.get_tags(tenant_id, entity_id)

        if self._client and self._merge_sha:
            timeout_s = _redis_merge_timeout_s()
            try:
                if timeout_s > 0:
                    eval_result = await asyncio.wait_for(
                        self._client.evalsha(
                            self._merge_sha, 1, key, str(TAGS_TTL_SECONDS), *new_tags
                        ),
                        timeout=timeout_s,
                    )
                else:
                    eval_result = await self._client.evalsha(
                        self._merge_sha, 1, key, str(TAGS_TTL_SECONDS), *new_tags
                    )
                return json.loads(eval_result) if eval_result else sorted(new_tags)
            except asyncio.TimeoutError as exc:
                if settings.strict_consistency:
                    raise ConnectionError(
                        "Redis merge_tags exceeded REDIS_MERGE_TIMEOUT_SECONDS while STRICT_CONSISTENCY is enabled",
                    ) from exc
                if self._kv_degraded is None:
                    raise ConnectionError(
                        "Redis merge_tags timed out (partition / slow path) and no KV fallback was configured via connect(kv_fallback=...)",
                    ) from exc
                log.warning(
                    "redis_merge_tags_timeout_failover_to_kv key=%s timeout_s=%s",
                    key,
                    timeout_s,
                )
                await self._redis_merge_failover_to_kv_reserve()
                if self._kv is None:
                    raise ConnectionError(
                        "KV failover store unavailable after Redis merge timeout"
                    ) from exc
                return await self._merge_tags_via_kv_store(self._kv, key, new_tags)
            except RedisError as exc:
                if settings.strict_consistency:
                    raise ConnectionError(
                        "Redis merge_tags failed while STRICT_CONSISTENCY is enabled",
                    ) from exc
                if self._kv_degraded is None:
                    raise ConnectionError(
                        "Redis merge_tags failed (cluster / connection drop) and no KV fallback was configured via connect(kv_fallback=...)",
                    ) from exc
                log.warning(
                    "redis_merge_tags_redis_error_failover_to_kv key=%s exc_type=%s",
                    key,
                    type(exc).__name__,
                )
                await self._redis_merge_failover_to_kv_reserve()
                if self._kv is None:
                    raise ConnectionError(
                        "KV failover store unavailable after Redis merge error"
                    ) from exc
                return await self._merge_tags_via_kv_store(self._kv, key, new_tags)

        if settings.strict_consistency:
            raise ConnectionError(
                "STRICT_CONSISTENCY is enabled but Redis is unavailable for atomic merge_tags"
            )

        if self._kv is None:
            raise ConnectionError(
                "merge_tags requires Redis or a KV fallback store (no backing store configured)"
            )

        return await self._merge_tags_via_kv_store(self._kv, key, new_tags)

    async def get_cached_score(self, tenant_id: str, entity_id: str) -> float | None:
        await self.connect()
        key = self._key_score(tenant_id, entity_id)
        if self._client:
            raw = await self._client.get(key)
        elif self._kv:
            raw = await self._kv.get(key)
        else:
            return None
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    async def set_cached_score(
        self, tenant_id: str, entity_id: str, score: float
    ) -> None:
        await self.connect()
        key = self._key_score(tenant_id, entity_id)
        if self._client:
            await self._client.setex(key, SCORE_TTL_SECONDS, str(score))
        elif self._kv:
            await self._kv.set(key, str(score), ttl_seconds=SCORE_TTL_SECONDS)

    # --- Attestation nonces ---

    async def store_nonce(self, nonce: str, ttl: int) -> None:
        await self.connect()
        key = f"{NONCE_PREFIX}{nonce}"
        if self._client:
            await self._client.setex(key, ttl, "1")
        elif self._kv:
            await self._kv.set(key, "1", ttl_seconds=int(ttl))

    async def consume_nonce(self, nonce: str) -> bool:
        """Atomically consume nonce — getdel ensures no double-use."""
        await self.connect()
        key = f"{NONCE_PREFIX}{nonce}"
        if self._client:
            val = await self._client.getdel(key)
            return val is not None

        if settings.strict_consistency:
            raise ConnectionError(
                "STRICT_CONSISTENCY is enabled but Redis is unavailable for atomic consume_nonce"
            )

        if self._kv is None:
            raise ConnectionError(
                "consume_nonce requires Redis or a KV fallback store (no backing store configured)"
            )

        lock_handle = await _kv_fallback_lock_acquire(self._fallback_lock_path)
        try:
            val = await self._kv.get(key)
            if not val:
                return False
            await self._kv.delete(key)
            return True
        finally:
            await _kv_fallback_lock_release(lock_handle)

    # --- Ingress replay detection ---
    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any]:
        """JSON flags keyed by tenant for kill-switches (R2.3). Empty if unset."""
        await self.connect()
        tkey = f"{TENANT_FLAGS_PREFIX}{tenant_id}"
        if self._client:
            raw = await self._client.get(tkey)
        elif self._kv:
            raw = await self._kv.get(tkey)
        else:
            return {}
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    async def set_tenant_flags(
        self, tenant_id: str, flags: dict[str, Any]
    ) -> dict[str, Any]:
        """Replace tenant flags document (admin / ops)."""
        await self.connect()
        key = f"{TENANT_FLAGS_PREFIX}{tenant_id}"
        blob = json.dumps(flags, sort_keys=True, default=str)
        if self._client:
            await self._client.set(key, blob)
        elif self._kv:
            await self._kv.set(key, blob, ttl_seconds=None)
        return dict(flags)

    async def patch_tenant_flags(
        self, tenant_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge updates into tenant flags."""
        cur = await self.get_tenant_flags(tenant_id)
        for k, v in updates.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        return await self.set_tenant_flags(tenant_id, cur)

    async def check_and_store_replay_signature(
        self,
        tenant_id: str,
        signature: str,
        ttl_seconds: int = 300,
    ) -> bool:
        """Returns True if signature already exists, otherwise stores and returns False."""
        await self.connect()
        key = f"{REPLAY_PREFIX}{tenant_id}:{signature}"
        ex = max(1, int(ttl_seconds))
        if self._client:
            created = await self._client.set(key, "1", ex=ex, nx=True)
            return created is None
        if self._kv:
            async with self._async_lock:
                if await self._kv.get(key):
                    return True
                await self._kv.set(key, "1", ttl_seconds=ex)
                return False
        return False

    # --- Consortium intelligence ---

    def _key_consortium(self, consortium_id: str, signal_hash: str) -> str:
        return f"{CONSORTIUM_PREFIX}{consortium_id}:{signal_hash}"

    def _key_consortium_tenant_trust(self, consortium_id: str) -> str:
        return f"{CONSORTIUM_PREFIX}{consortium_id}:tenant_trust"

    async def _kv_trust_lookup_nolock(
        self, consortium_id: str, tenant_id: str
    ) -> float:
        """Read tenant trust from the JSON trust-map key (caller serializes writes for Micro)."""
        if not self._kv:
            return 1.0
        raw = await self._kv.get(self._key_consortium_tenant_trust(consortium_id))
        if not raw:
            return 1.0
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and tenant_id in obj:
                return max(0.1, min(2.0, float(obj[tenant_id])))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            InternalMonitor.log_suppressed_error(
                exc,
                context="consortium_trust_map_kv_lookup",
                domain="fraud_decisioning",
                level=logging.DEBUG,
                consortium_id=consortium_id,
                tenant_id=tenant_id,
            )
        return 1.0

    async def set_consortium_tenant_trust(
        self,
        consortium_id: str,
        tenant_id: str,
        trust_score: float,
    ) -> dict[str, Any]:
        await self.connect()
        key = self._key_consortium_tenant_trust(consortium_id)
        score = max(0.1, min(2.0, float(trust_score)))
        if self._client:
            await self._client.hset(key, tenant_id, str(score))
        elif self._kv:
            async with self._async_lock:
                raw = await self._kv.get(key)
                tmap: dict[str, float] = {}
                if raw:
                    try:
                        obj = json.loads(raw)
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                try:
                                    tmap[str(k)] = max(0.1, min(2.0, float(v)))
                                except (TypeError, ValueError):
                                    continue
                    except json.JSONDecodeError as exc:
                        InternalMonitor.log_suppressed_error(
                            exc,
                            context="consortium_trust_map_json_corrupt",
                            domain="fraud_decisioning",
                            level=logging.DEBUG,
                            consortium_id=consortium_id,
                        )
                tmap[tenant_id] = score
                await self._kv.set(key, json.dumps(tmap), ttl_seconds=None)
        return {
            "consortium_id": consortium_id,
            "tenant_id": tenant_id,
            "trust_score": score,
        }

    async def get_consortium_tenant_trust(
        self, consortium_id: str, tenant_id: str
    ) -> float:
        await self.connect()
        if self._client:
            key = self._key_consortium_tenant_trust(consortium_id)
            raw = await self._client.hget(key, tenant_id)
            if raw is None:
                return 1.0
            try:
                return max(0.1, min(2.0, float(raw)))
            except ValueError:
                return 1.0
        if self._kv:
            return await self._kv_trust_lookup_nolock(consortium_id, tenant_id)
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
        key = self._key_consortium(consortium_id, signal_hash)
        ttl = max(1, int(ttl_days)) * 86400

        async def _body(raw: str | None, trust_seed: float) -> dict[str, Any]:
            current: dict[str, Any] = json.loads(raw) if raw else {}
            tenants = set(current.get("tenants", []))
            tenants.add(reporter_tenant)
            signal_counts = dict(current.get("signal_counts", {}))
            signal_counts[signal_type] = int(signal_counts.get(signal_type, 0)) + 1
            report_count = int(current.get("report_count", 0)) + 1
            max_severity = max(float(current.get("max_severity", 0.0)), float(severity))
            trust_map = dict(current.get("tenant_trust", {}))
            if reporter_tenant not in trust_map:
                trust_map[reporter_tenant] = trust_seed
            return _consortium_metrics_recompute(
                {
                    "consortium_id": consortium_id,
                    "tenants": sorted(tenants),
                    "tenant_trust": trust_map,
                    "signal_counts": signal_counts,
                    "report_count": report_count,
                    "max_severity": max_severity,
                    "weighted_report_score": float(
                        current.get("weighted_report_score", 0.0)
                    )
                    + float(trust_map[reporter_tenant]),
                    "false_positive_count": int(current.get("false_positive_count", 0)),
                    "confirmed_fraud_count": int(
                        current.get("confirmed_fraud_count", 0)
                    ),
                }
            )

        if self._client:
            raw = await self._client.get(key)
            seed = await self.get_consortium_tenant_trust(
                consortium_id, reporter_tenant
            )
            updated = await _body(raw, seed)
            await self._client.setex(key, ttl, json.dumps(updated))
            return updated
        if self._kv:
            async with self._async_lock:
                raw = await self._kv.get(key)
                seed = await self._kv_trust_lookup_nolock(
                    consortium_id, reporter_tenant
                )
                updated = await _body(raw, seed)
                await self._kv.set(key, json.dumps(updated), ttl_seconds=ttl)
                return updated
        return {
            "consortium_id": consortium_id,
            "tenant_count": 0,
            "tenants": [],
            "tenant_trust": {},
            "signal_counts": {},
            "report_count": 0,
            "max_severity": 0.0,
            "weighted_report_score": 0.0,
            "false_positive_count": 0,
            "confirmed_fraud_count": 0,
            "false_positive_rate": 0.0,
            "quality_score": 0.2,
        }

    async def check_consortium_signal(
        self, consortium_id: str, signal_hash: str
    ) -> dict[str, Any]:
        await self.connect()
        key = self._key_consortium(consortium_id, signal_hash)
        if self._client:
            raw = await self._client.get(key)
        elif self._kv:
            raw = await self._kv.get(key)
        else:
            raw = None
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
        key = self._key_consortium(consortium_id, signal_hash)
        ttl = max(1, int(ttl_days)) * 86400

        def _mutate(current: dict[str, Any]) -> dict[str, Any]:
            fp = int(current.get("false_positive_count", 0))
            cf = int(current.get("confirmed_fraud_count", 0))
            if outcome == "false_positive":
                fp += 1
            elif outcome == "confirmed_fraud":
                cf += 1
            current["false_positive_count"] = fp
            current["confirmed_fraud_count"] = cf
            return _consortium_metrics_recompute(current)

        if self._client:
            raw = await self._client.get(key)
            current: dict[str, Any] = json.loads(raw) if raw else {}
            current = _mutate(current)
            await self._client.setex(key, ttl, json.dumps(current))
        elif self._kv:
            async with self._async_lock:
                raw = await self._kv.get(key)
                current = json.loads(raw) if raw else {}
                current = _mutate(current)
                await self._kv.set(key, json.dumps(current), ttl_seconds=ttl)
        else:
            current = _mutate({"consortium_id": consortium_id})
        current.pop("tenants", None)
        current.pop("tenant_trust", None)
        return current


redis_tags = RedisTags(settings.redis_url)
