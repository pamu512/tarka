"""E-hailing host-action ladder: hard_challenge → suspend_driving after N repeats.

Deterministic in-process counter with optional Redis; no LIVE face vendor required.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import redis.asyncio as aioredis

log = logging.getLogger("decision-api.ehailing_escalation")

_PREFIX = "fraud:eh_challenge:"
_TTL = 86400 * 90
# ponytail: global threshold; per-tenant override via metadata.ehailing_challenge_threshold
_DEFAULT_THRESHOLD = int(os.environ.get("TARKA_EHAILING_CHALLENGE_SUSPEND_AFTER", "3"))


class EhailingChallengeStore:
    """Count hard_challenge hits per tenant+driver; Redis or memory."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._memory: dict[str, int] = {}
        self._lock = threading.Lock()

    def set_client(self, client: aioredis.Redis | None) -> None:
        self._client = client

    def clear_memory_for_tests(self) -> None:
        with self._lock:
            self._memory.clear()

    def _key(self, tenant_id: str, actor_id: str) -> str:
        return f"{_PREFIX}{tenant_id.strip()}:{actor_id.strip()}"

    def backend(self) -> str:
        return "redis" if self._client is not None else "memory"

    async def get_count(self, tenant_id: str, actor_id: str) -> int:
        key = self._key(tenant_id, actor_id)
        if self._client is not None:
            try:
                raw = await self._client.get(key)
                if raw is not None:
                    return int(raw)
            except Exception:
                log.warning("eh_challenge_redis_get_failed key=%s", key, exc_info=True)
        with self._lock:
            return int(self._memory.get(key) or 0)

    async def incr(self, tenant_id: str, actor_id: str) -> int:
        key = self._key(tenant_id, actor_id)
        if self._client is not None:
            try:
                n = await self._client.incr(key)
                await self._client.expire(key, _TTL)
                with self._lock:
                    self._memory[key] = int(n)
                return int(n)
            except Exception:
                log.warning("eh_challenge_redis_incr_failed key=%s", key, exc_info=True)
        with self._lock:
            n = int(self._memory.get(key) or 0) + 1
            self._memory[key] = n
            return n


ehailing_challenge_store = EhailingChallengeStore()


def _vertical_is_ehailing(metadata: dict[str, Any] | None, features: dict[str, Any]) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    v = (
        meta.get("vertical_profile")
        or meta.get("vertical")
        or features.get("vertical_profile")
        or features.get("vertical")
    )
    s = str(v or "").strip().lower()
    return s in ("e_hailing", "ride_hailing", "ehailing")


def _actor_id(
    *,
    entity_id: str,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> str:
    pl = payload if isinstance(payload, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}
    for key in ("driver_id", "actor_id", "worker_id"):
        val = pl.get(key) or meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return (entity_id or "").strip() or "unknown"


def _threshold(metadata: dict[str, Any] | None) -> int:
    meta = metadata if isinstance(metadata, dict) else {}
    raw = meta.get("ehailing_challenge_threshold")
    if raw is not None:
        try:
            n = int(raw)
            if n >= 1:
                return n
        except (TypeError, ValueError):
            pass
    return max(1, _DEFAULT_THRESHOLD)


async def apply_ehailing_challenge_escalation(
    *,
    tenant_id: str,
    entity_id: str,
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    tags: list[str],
    rule_hits: list[str],
) -> dict[str, Any] | None:
    """If hard_challenge on e-hailing, count repeats; escalate to suspend_driving."""
    if not _vertical_is_ehailing(metadata, features):
        return None
    challenge_hits = (
        "eh_self_ride_same_device",
        "eh_driver_rider_pair_velocity",
        "eh_location_spoof",
    )
    has_challenge = "action:hard_challenge" in tags or any(
        h in rule_hits for h in challenge_hits
    )
    if not has_challenge:
        return None

    actor = _actor_id(entity_id=entity_id, payload=payload, metadata=metadata)
    if not actor or actor == "unknown":
        return None

    if "action:hard_challenge" not in tags:
        tags.append("action:hard_challenge")

    count = await ehailing_challenge_store.incr(tenant_id, actor)
    thr = _threshold(metadata)
    features["eh_challenge_count"] = count
    features["eh_challenge_threshold"] = thr
    evidence: dict[str, Any] = {
        "schema_id": "tarka.ehailing_escalation/v1",
        "method": "repeat_counter_v1",
        "actor_id": actor,
        "challenge_count": count,
        "suspend_after": thr,
        "backend": ehailing_challenge_store.backend(),
        "live_claim_allowed": False,
    }
    if count >= thr:
        features["eh_escalate_suspend_driving"] = True
        if "action:suspend_driving" not in tags:
            tags.append("action:suspend_driving")
        if "eh_challenge_escalate_suspend" not in rule_hits:
            rule_hits.append("eh_challenge_escalate_suspend")
        evidence["escalated"] = True
        evidence["host_action"] = "suspend_driving"
    else:
        evidence["escalated"] = False
        evidence["host_action"] = "hard_challenge"
    return evidence
