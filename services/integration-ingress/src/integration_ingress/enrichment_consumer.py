"""NATS consumer: run OSINT asynchronously and persist results to Redis for decision-api evaluate path."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis

from integration_ingress.config import settings
from integration_ingress.osint import OsintConfig, full_osint_enrichment

log = logging.getLogger(__name__)

ASYNC_OSINT_REDIS_KEY = "fraud:async_osint:{tenant_id}:{entity_id}"


def _osint_cfg() -> OsintConfig:
    return OsintConfig(
        abuseipdb_key=settings.abuseipdb_key,
        greynoise_key=settings.greynoise_key,
        emailrep_key=settings.emailrep_key,
        numverify_key=settings.numverify_key,
        ipinfo_token=settings.ipinfo_token,
    )


async def _handle_enrichment_message(msg: Any, http: httpx.AsyncClient, redis: Any) -> None:
    try:
        data = json.loads(msg.data.decode("utf-8"))
    except Exception as e:
        log.warning("enrichment message decode failed: %s", e)
        return
    if not isinstance(data, dict):
        return
    if data.get("schema") != "tarka.enrichment.request/v1":
        return
    tenant_id = str(data.get("tenant_id") or "").strip()
    entity_id = str(data.get("entity_id") or "").strip()
    if not tenant_id or not entity_id:
        return
    email = data.get("email")
    phone = data.get("phone")
    ip = data.get("ip")
    domain = data.get("domain")
    if not any((email, phone, ip, domain)):
        return
    cfg = _osint_cfg()
    try:
        osint_result = await full_osint_enrichment(
            email=str(email).strip() if email else None,
            phone=str(phone).strip() if phone else None,
            ip=str(ip).strip() if ip else None,
            domain=str(domain).strip() if domain else None,
            http=http,
            cfg=cfg,
        )
    except Exception as e:
        log.warning("full_osint_enrichment failed tenant=%s entity=%s: %s", tenant_id, entity_id, e)
        return
    if isinstance(osint_result, dict) and osint_result.get("error"):
        return
    key = ASYNC_OSINT_REDIS_KEY.format(tenant_id=tenant_id, entity_id=entity_id)
    blob = {
        "osint": osint_result,
        "trace_id": data.get("trace_id"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await redis.set(
            key,
            json.dumps(blob, default=str),
            ex=max(60, int(settings.async_enrichment_redis_ttl_seconds)),
        )
    except Exception as e:
        log.warning("redis write failed for async osint %s: %s", key, e)


async def run_enrichment_consumer(
    *,
    nc: Any,
    http: httpx.AsyncClient,
) -> None:
    """Subscribe to core NATS subject and process enrichment requests until cancelled."""
    url = (settings.redis_url or "").strip()
    if not url:
        log.warning("enrichment consumer disabled: REDIS_URL empty")
        return
    redis = aioredis.from_url(url, decode_responses=True)
    try:
        loop = asyncio.get_running_loop()

        def _cb(msg: Any) -> None:
            loop.create_task(_handle_enrichment_message(msg, http, redis))

        await nc.subscribe("fraud.enrichment.request", cb=_cb)
        log.info("enrichment consumer subscribed to fraud.enrichment.request")
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("enrichment consumer cancelled")
        raise
    finally:
        await redis.aclose()
