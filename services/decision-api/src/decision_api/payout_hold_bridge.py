"""Evaluate → integration-ingress payout hold bridge (Marketplace P0)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("decision-api.payout_hold_bridge")

ACTION_TAGS = frozenset({"action:payout_hold", "action:payout_delay"})
PAYOUT_CHECKPOINTS = frozenset({"payout"})
DEFAULT_HOLD_HOURS = 72
DEFAULT_DELAY_HOURS = 24


def should_create_payout_hold(
    *,
    metadata: dict[str, Any] | None,
    tags: list[str] | None,
    event_type: str | None = None,
) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    et = str(event_type or "").strip().lower()
    if checkpoint not in PAYOUT_CHECKPOINTS and et not in PAYOUT_CHECKPOINTS:
        return False
    return bool(set(tags or []) & ACTION_TAGS)


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
    payout_id = str(meta.get("payout_id") or "").strip()
    if not payout_id:
        raise ValueError("metadata.payout_id is required for payout hold bridge")

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
    if not str(meta.get("payout_id") or "").strip():
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
    )
