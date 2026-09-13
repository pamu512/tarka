"""Deploy shadow hypotheses to Redis (Prompt 192).

Redis is the sole delivery channel — live reader: ``services/shadow``
``shadow_hypothesis.py``. The NATS ``tarka.hypothesis.deployed`` publish
and the Rust watcher it claimed to notify never shipped a consumer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REDIS_KEY = "shadow:rules:active"


def _redis_url() -> str | None:
    raw = (
        os.environ.get("SHADOW_RULES_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or os.environ.get("ANUMANA_REDIS_URL")
        or ""
    ).strip()
    return raw or None


async def publish_hypothesis_deployed(
    *,
    rules: list[dict[str, Any]],
    tenant_id: str = "default",
    version: int | None = None,
    redis_key: str = DEFAULT_REDIS_KEY,
) -> dict[str, Any]:
    """
    Persist active shadow rules to Redis (sole delivery channel; the
    ``tarka.hypothesis.deployed`` NATS publish had no consumer and was removed).
    """
    redis_url = _redis_url()
    if redis_url is None:
        raise RuntimeError("SHADOW_RULES_REDIS_URL or REDIS_URL required for hypothesis deploy")

    import redis.asyncio as redis_mod

    client = redis_mod.from_url(redis_url, decode_responses=True)
    try:
        await client.set(redis_key, json.dumps(rules, separators=(",", ":"), default=str))
    finally:
        await client.aclose()

    logger.info(
        "hypothesis_deployed_redis redis_key=%s rule_count=%s version=%s",
        redis_key,
        len(rules),
        version,
    )

    return {
        "ok": True,
        "redis_key": redis_key,
        "rule_count": len(rules),
        "version": version,
    }
