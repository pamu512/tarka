"""Deploy shadow hypotheses to Redis and notify the Rust hot-reload watcher via NATS (Prompt 192)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SUBJECT = "tarka.hypothesis.deployed"
DEFAULT_REDIS_KEY = "shadow:rules:active"


def _nats_url() -> str | None:
    raw = (os.environ.get("RULE_ENGINE_NATS_URL") or os.environ.get("NATS_URL") or "").strip()
    return raw or None


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
    Persist active shadow rules to Redis and publish ``hypothesis_deployed`` on NATS.

    The Rust ``tarka-rule-engine-watcher`` binary reloads its in-memory :class:`RuleSet` without
    dropping the NATS connection.
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

    subject = (os.environ.get("RULE_ENGINE_HYPOTHESIS_DEPLOY_SUBJECT") or DEFAULT_SUBJECT).strip()
    payload: dict[str, Any] = {
        "event": "hypothesis_deployed",
        "tenant_id": tenant_id,
        "redis_key": redis_key,
        "rules": rules,
    }
    if version is not None:
        payload["version"] = int(version)

    nats_url = _nats_url()
    if nats_url:
        import nats

        nc = await nats.connect(nats_url)
        try:
            await nc.publish(subject, json.dumps(payload, default=str).encode("utf-8"))
            await nc.flush()
        finally:
            await nc.drain()
        logger.info(
            "hypothesis_deployed_published subject=%s rule_count=%s version=%s",
            subject,
            len(rules),
            version,
        )
    else:
        logger.warning(
            "hypothesis_deployed_nats_skipped_no_url redis_key=%s rule_count=%s",
            redis_key,
            len(rules),
        )

    return {
        "ok": True,
        "redis_key": redis_key,
        "rule_count": len(rules),
        "nats_subject": subject if nats_url else None,
        "version": version,
    }
