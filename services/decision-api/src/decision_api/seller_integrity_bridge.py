"""Evaluate → integration-ingress seller integrity bridge (Marketplace B3)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("decision-api.seller_integrity_bridge")

SELLER_CHECKPOINTS = frozenset({"seller_review", "delivery", "checkout"})
DEFAULT_WINDOW_DAYS = 30


def _int_field(meta: dict[str, Any], key: str, default: int = 0) -> int:
    raw = meta.get(key)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def should_record_seller_integrity(
    *,
    metadata: dict[str, Any] | None,
    event_type: str | None = None,
) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    seller_id = str(meta.get("seller_id") or "").strip()
    if not seller_id:
        return False
    has_counts = (
        meta.get("successful_deliveries") is not None
        or meta.get("review_count") is not None
    )
    if has_counts:
        return True
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    et = str(event_type or "").strip().lower()
    return checkpoint in SELLER_CHECKPOINTS or et in SELLER_CHECKPOINTS


def build_seller_payload(
    *,
    tenant_id: str,
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(metadata if isinstance(metadata, dict) else {})
    pl = payload if isinstance(payload, dict) else {}
    for key in (
        "seller_id",
        "successful_deliveries",
        "review_count",
        "window_days",
        "display_name",
        "store_slug",
        "category",
        "avg_rating",
    ):
        if key not in meta and key in pl:
            meta[key] = pl[key]

    seller_id = str(meta.get("seller_id") or "").strip()
    if not seller_id:
        raise ValueError("metadata.seller_id is required for seller integrity bridge")

    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "seller_id": seller_id,
        "successful_deliveries": _int_field(meta, "successful_deliveries"),
        "review_count": _int_field(meta, "review_count"),
        "window_days": _int_field(meta, "window_days", DEFAULT_WINDOW_DAYS)
        or DEFAULT_WINDOW_DAYS,
    }
    for optional in ("display_name", "store_slug", "category"):
        val = meta.get(optional)
        if isinstance(val, str) and val.strip():
            body[optional] = val.strip()
    avg_rating = meta.get("avg_rating")
    if avg_rating is not None:
        try:
            body["avg_rating"] = float(avg_rating)
        except (TypeError, ValueError):
            pass
    return body


async def maybe_record_seller_integrity(
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
            f"{url_base.rstrip('/')}/v1/internal/marketplace/seller-integrity",
            json=payload,
            headers={"X-Internal-Token": secret},
            timeout=2.0,
        )
        r.raise_for_status()
    except Exception:
        log.exception("seller_integrity_bridge_failed")
        if callable(metrics_inc):
            metrics_inc("seller_integrity_bridge_failed")


async def maybe_record_seller_integrity_from_evaluate(
    *,
    http: Any,
    integration_ingress_url: str,
    ingress_internal_token: str,
    tenant_id: str,
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    trace_id: str,
    event_type: str = "",
    metrics_inc: Any = None,
) -> None:
    if not should_record_seller_integrity(metadata=metadata, event_type=event_type):
        return
    try:
        body = build_seller_payload(
            tenant_id=tenant_id,
            metadata=metadata,
            payload=payload,
        )
    except ValueError:
        log.warning(
            "seller_integrity_bridge_skipped invalid payload tenant_id=%s trace_id=%s",
            tenant_id,
            trace_id,
            exc_info=True,
        )
        return
    await maybe_record_seller_integrity(
        http=http,
        base_url=integration_ingress_url,
        token=ingress_internal_token,
        payload=body,
        metrics_inc=metrics_inc,
    )
