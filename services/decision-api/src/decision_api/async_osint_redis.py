"""Read async OSINT payloads materialized by integration-ingress into Redis (no HTTP on evaluate path)."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

log = logging.getLogger(__name__)

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from osint_flatten import flatten_light_enrichment_response, flatten_osint_response  # noqa: E402

# Same key shape written by integration-ingress enrichment worker.
ASYNC_OSINT_REDIS_KEY = "fraud:async_osint:{tenant_id}:{entity_id}"


async def merge_cached_async_osint(
    redis_client: Any,
    tenant_id: str,
    entity_id: str,
    features: dict[str, Any],
) -> None:
    """Merge cached OSINT-derived features from Redis into *features* (in-place)."""
    if redis_client is None:
        return
    key = ASYNC_OSINT_REDIS_KEY.format(tenant_id=tenant_id, entity_id=entity_id)
    try:
        raw = await redis_client.get(key)
    except Exception as e:  # pragma: no cover — network
        log.debug("async osint redis read failed: %s", e)
        return
    if not raw:
        return
    try:
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8")
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return
    if not isinstance(blob, dict):
        return
    osint_block = blob.get("osint")
    if isinstance(osint_block, dict):
        features.update(flatten_osint_response(osint_block))
    elif "composite_risk_score" in blob or "enrichments" in blob:
        # Legacy / direct full_osint payload
        features.update(flatten_osint_response(blob))
    enrich_block = blob.get("enrich")
    if isinstance(enrich_block, dict):
        features.update(flatten_light_enrichment_response(enrich_block))


async def publish_async_enrichment_request(app_state: Any, body: Any, trace_id: Any) -> None:
    """Fire-and-forget NATS message so integration-ingress can refresh Redis OSINT (core NATS)."""
    nc = getattr(app_state, "nats_nc", None)
    if nc is None:
        return
    payload = body.payload if isinstance(body.payload, dict) else {}
    meta = body.metadata if isinstance(body.metadata, dict) else {}
    msg = {
        "schema": "tarka.enrichment.request/v1",
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "trace_id": str(trace_id),
        "email": (str(payload.get("email")).strip() if payload.get("email") else None),
        "phone": (str(payload.get("phone")).strip() if payload.get("phone") else None),
        "ip": (str(payload.get("ip") or payload.get("ip_address") or "").strip() or None),
        "domain": (str(payload.get("domain")).strip() if payload.get("domain") else None),
    }
    # Drop empty-only messages
    if not any(msg.get(k) for k in ("email", "phone", "ip", "domain")):
        return
    try:
        import json as _json

        await nc.publish("fraud.enrichment.request", _json.dumps(msg, default=str).encode("utf-8"))
    except Exception as e:  # pragma: no cover
        log.warning("enrichment request publish failed: %s", e)
