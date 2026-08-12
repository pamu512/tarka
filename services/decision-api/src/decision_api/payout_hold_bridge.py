"""Evaluate → integration-ingress payout hold bridge (Marketplace P0)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("decision-api.payout_hold_bridge")

ACTION_TAGS = frozenset({"action:payout_hold", "action:payout_delay"})
HOLD_CHECKPOINTS = frozenset({"payout", "dispatch", "deliver", "delivery"})
SPOOF_RISK_TAGS = frozenset({"risk:courier_spoof", "action:payout_hold"})
DEFAULT_HOLD_HOURS = 72
DEFAULT_DELAY_HOURS = 24


def _resolve_checkpoint(meta: dict[str, Any], event_type: str | None = None) -> str:
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    if checkpoint:
        return checkpoint
    return str(event_type or "").strip().lower()


def _has_spoof_risk_tag(tags: list[str] | None) -> bool:
    for tag in tags or []:
        if tag in SPOOF_RISK_TAGS or tag.startswith("vendor:incognia"):
            return True
    return False


def _resolve_payout_id(meta: dict[str, Any]) -> str:
    for key in ("payout_id", "courier_payout_id", "transfer_id"):
        val = str(meta.get(key) or "").strip()
        if val:
            return val
    return ""


def should_create_payout_hold(
    *,
    metadata: dict[str, Any] | None,
    tags: list[str] | None,
    event_type: str | None = None,
) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    checkpoint = _resolve_checkpoint(meta, event_type)
    if checkpoint not in HOLD_CHECKPOINTS:
        return False
    tag_list = tags or []
    if checkpoint == "payout":
        return bool(set(tag_list) & ACTION_TAGS)
    return _has_spoof_risk_tag(tag_list)


def resolve_hold_status_and_hours(tags: list[str] | None) -> tuple[str, int]:
    tag_set = set(tags or [])
    if "action:payout_hold" in tag_set:
        return "held", DEFAULT_HOLD_HOURS
    if "action:payout_delay" in tag_set:
        return "pending", DEFAULT_DELAY_HOURS
    return "held", DEFAULT_HOLD_HOURS


def _hold_reason_from_tags(tags: list[str]) -> str:
    for tag in tags:
        if tag in ACTION_TAGS:
            return f"tag:{tag}"
    for tag in tags:
        if tag.startswith("action:payout_"):
            return f"tag:{tag}"
    return "tag:action:payout_hold"


def build_hold_payload(
    *,
    tenant_id: str,
    entity_id: str,
    tags: list[str],
    metadata: dict[str, Any] | None,
    decision_id: str,
    trace_id: str,
) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    payout_id = _resolve_payout_id(meta)
    if not payout_id:
        raise ValueError(
            "metadata payout_id, courier_payout_id, or transfer_id is required "
            "for payout hold bridge"
        )

    status, hold_duration_hours = resolve_hold_status_and_hours(tags)

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "payout_id": payout_id,
        "entity_id": entity_id,
        "status": status,
        "hold_duration_hours": hold_duration_hours,
        "hold_reason": _hold_reason_from_tags(list(tags)),
        "held_by": "evaluate",
        "decision_id": decision_id,
        "trace_id": trace_id,
        "tags": list(tags),
    }
    amount = meta.get("amount")
    if amount is not None:
        try:
            payload["amount"] = float(amount)
        except (TypeError, ValueError):
            pass
    currency = meta.get("currency")
    if isinstance(currency, str) and currency.strip():
        payload["currency"] = currency.strip()
    return payload


async def maybe_create_payout_hold(
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
            f"{url_base.rstrip('/')}/v1/internal/marketplace/payout-holds",
            json=payload,
            headers={"X-Internal-Token": secret},
            timeout=2.0,
        )
        r.raise_for_status()
    except Exception:
        log.exception("payout_hold_bridge_failed")
        if callable(metrics_inc):
            metrics_inc("payout_hold_bridge_failed")


async def maybe_create_payout_hold_from_evaluate(
    *,
    http: Any,
    integration_ingress_url: str,
    ingress_internal_token: str,
    tenant_id: str,
    entity_id: str,
    tags: list[str],
    metadata: dict[str, Any] | None,
    trace_id: str,
    event_type: str = "",
    metrics_inc: Any = None,
) -> None:
    if not should_create_payout_hold(
        metadata=metadata, tags=tags, event_type=event_type
    ):
        return
    meta = metadata if isinstance(metadata, dict) else {}
    if not _resolve_payout_id(meta):
        log.warning(
            "payout_hold_bridge_skipped missing payout_id tenant_id=%s trace_id=%s",
            tenant_id,
            trace_id,
        )
        return
    try:
        payload = build_hold_payload(
            tenant_id=tenant_id,
            entity_id=entity_id,
            tags=tags,
            metadata=metadata,
            decision_id=trace_id,
            trace_id=trace_id,
        )
    except ValueError:
        log.warning(
            "payout_hold_bridge_skipped invalid payload tenant_id=%s trace_id=%s",
            tenant_id,
            trace_id,
            exc_info=True,
        )
        return
    await maybe_create_payout_hold(
        http=http,
        base_url=integration_ingress_url,
        token=ingress_internal_token,
        payload=payload,
        metrics_inc=metrics_inc,
    )
