"""Evaluate → integration-ingress promo redemption bridge (Marketplace B3)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("decision-api.promo_redemption_bridge")

PROMO_CHECKPOINTS = frozenset({"redeem", "promo"})
PROMO_FARM_TAG = "risk:promo_farm"


def _coupon_from_metadata(metadata: dict[str, Any]) -> str:
    return str(metadata.get("coupon_code") or metadata.get("promo_code") or "").strip()


def should_record_promo_redemption(
    *,
    metadata: dict[str, Any] | None,
    tags: list[str] | None,
    event_type: str | None = None,
) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    if not _coupon_from_metadata(meta):
        return False
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    et = str(event_type or "").strip().lower()
    if checkpoint in PROMO_CHECKPOINTS or et in PROMO_CHECKPOINTS:
        return True
    return PROMO_FARM_TAG in set(tags or [])


def build_promo_payload(
    *,
    tenant_id: str,
    entity_id: str,
    tags: list[str],
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    trace_id: str,
) -> dict[str, Any]:
    meta = dict(metadata if isinstance(metadata, dict) else {})
    pl = payload if isinstance(payload, dict) else {}
    for key in (
        "coupon_code",
        "promo_code",
        "device_id",
        "order_total",
        "currency",
        "ip_hint",
        "ip",
        "ip_address",
    ):
        if key not in meta and key in pl:
            meta[key] = pl[key]

    coupon = _coupon_from_metadata(meta)
    if not coupon:
        raise ValueError("metadata.coupon_code or metadata.promo_code is required")

    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "coupon_code": coupon,
        "user_id": entity_id,
        "flags": list(tags),
        "trace_id": trace_id,
    }
    device_id = str(meta.get("device_id") or "").strip()
    if device_id:
        body["device_id"] = device_id
    order_total = meta.get("order_total")
    if order_total is not None:
        try:
            body["order_total"] = float(order_total)
        except (TypeError, ValueError):
            pass
    currency = meta.get("currency")
    if isinstance(currency, str) and currency.strip():
        body["currency"] = currency.strip()
    ip_hint = str(
        meta.get("ip_hint") or meta.get("ip") or meta.get("ip_address") or ""
    ).strip()
    if ip_hint:
        body["ip_hint"] = ip_hint
    return body


async def maybe_record_promo_redemption(
    *,
    http: Any,
    base_url: str,
    token: str,
    payload: dict[str, Any],
    metrics_inc: Any = None,
) -> None:
    url_base = (base_url or "").strip()
    secret = (token or "").strip()
    if not url_base or not secret:
        return
    try:
        r = await http.post(
            f"{url_base.rstrip('/')}/v1/internal/marketplace/promo-redemptions",
            json=payload,
            headers={"X-Internal-Token": secret},
            timeout=2.0,
        )
        r.raise_for_status()
    except Exception:
        log.exception("promo_redemption_bridge_failed")
        if callable(metrics_inc):
            metrics_inc("promo_redemption_bridge_failed")


async def maybe_record_promo_redemption_from_evaluate(
    *,
    http: Any,
    integration_ingress_url: str,
    ingress_internal_token: str,
    tenant_id: str,
    entity_id: str,
    tags: list[str],
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    trace_id: str,
    event_type: str = "",
    metrics_inc: Any = None,
) -> None:
    if not should_record_promo_redemption(
        metadata=metadata, tags=tags, event_type=event_type
    ):
        return
    meta = metadata if isinstance(metadata, dict) else {}
    if not _coupon_from_metadata(meta):
        log.warning(
            "promo_redemption_bridge_skipped missing coupon tenant_id=%s trace_id=%s",
            tenant_id,
            trace_id,
        )
        return
    try:
        body = build_promo_payload(
            tenant_id=tenant_id,
            entity_id=entity_id,
            tags=tags,
            metadata=metadata,
            payload=payload,
            trace_id=trace_id,
        )
    except ValueError:
        log.warning(
            "promo_redemption_bridge_skipped invalid payload tenant_id=%s trace_id=%s",
            tenant_id,
            trace_id,
            exc_info=True,
        )
        return
    await maybe_record_promo_redemption(
        http=http,
        base_url=integration_ingress_url,
        token=ingress_internal_token,
        payload=body,
        metrics_inc=metrics_inc,
    )
