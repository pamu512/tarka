"""Read async OSINT payloads materialized by integration-ingress into Redis (no HTTP on evaluate path)."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Callable

from decision_api.async_enrich_freshness import evaluate_async_enrich_freshness

log = logging.getLogger(__name__)

_shared_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared")
)
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from osint_flatten import flatten_light_enrichment_response, flatten_osint_response  # noqa: E402

# Same key shape written by integration-ingress enrichment worker.
ASYNC_OSINT_REDIS_KEY = "fraud:async_osint:{tenant_id}:{entity_id}"


def _apply_blob_to_features(blob: dict[str, Any], features: dict[str, Any]) -> None:
    osint_block = blob.get("osint")
    if isinstance(osint_block, dict):
        features.update(flatten_osint_response(osint_block))
    elif "composite_risk_score" in blob or "enrichments" in blob:
        features.update(flatten_osint_response(blob))
    enrich_block = blob.get("enrich")
    if isinstance(enrich_block, dict):
        features.update(flatten_light_enrichment_response(enrich_block))


async def merge_cached_async_osint(
    redis_client: Any,
    tenant_id: str,
    entity_id: str,
    features: dict[str, Any],
    *,
    degrade_tags: list[str] | None = None,
    max_age_minutes: int = 0,
    metrics_inc: Callable[..., Any] | None = None,
) -> None:
    """Merge cached OSINT-derived features from Redis into *features* (in-place).

    When ``max_age_minutes > 0`` and blob ``updated_at`` is stale, append
    ``async_enrich:stale`` (fail soft — features still merge) and emit a metric.
    """
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

    if max_age_minutes > 0:
        freshness = evaluate_async_enrich_freshness(
            blob,
            max_age_minutes=max_age_minutes,
            tenant_id=tenant_id,
            entity_id=entity_id,
        )
        if freshness.action == "stale":
            if degrade_tags is not None and "async_enrich:stale" not in degrade_tags:
                degrade_tags.append("async_enrich:stale")
            if metrics_inc is not None:
                try:
                    metrics_inc("tarka_async_enrich_stale_total")
                except Exception:
                    log.debug("async_enrich_stale_metric_failed", exc_info=True)

    _apply_blob_to_features(blob, features)


async def publish_async_enrichment_request(
    broker: Any,
    body: Any,
    trace_id: Any,
    *,
    tenant_flags: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget enrichment refresh via the configured :class:`tarka_core.messaging.MessageBroker`."""
    if broker is None:
        return
    from tarka_core.messaging import PublishDelivery

    payload = body.payload if isinstance(body.payload, dict) else {}
    tf = tenant_flags or {}
    dr = str(tf.get("data_residency_region") or "").strip().upper()
    msg = {
        "schema": "tarka.enrichment.request/v1",
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "trace_id": str(trace_id),
        "email": (str(payload.get("email")).strip() if payload.get("email") else None),
        "phone": (str(payload.get("phone")).strip() if payload.get("phone") else None),
        "ip": (
            str(payload.get("ip") or payload.get("ip_address") or "").strip() or None
        ),
        "domain": (
            str(payload.get("domain")).strip() if payload.get("domain") else None
        ),
    }
    if dr in ("EU", "US", "GLOBAL"):
        msg["data_residency_region"] = dr
    if not any(msg.get(k) for k in ("email", "phone", "ip", "domain")):
        return
    try:
        import json as _json

        await broker.publish(
            "fraud.enrichment.request",
            _json.dumps(msg, default=str).encode("utf-8"),
            delivery=PublishDelivery.CORE,
        )
    except Exception as e:  # pragma: no cover
        log.warning("enrichment request publish failed: %s", e)
