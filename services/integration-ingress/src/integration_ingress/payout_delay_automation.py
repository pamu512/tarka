"""Payout delay automation — hold funds when JanusGraph mule_score is high (Prompt 183)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.payout_hold_store import list_holds, release_hold, upsert_hold

DEFAULT_MULE_SCORE_HOLD_THRESHOLD = 72
DEFAULT_PAYOUT_LIMIT = 35
DEFAULT_DELAY_HOURS = 24
JANUS_PROPERTY = "mule_score"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_CONFIG_BY_TENANT: dict[str, dict[str, Any]] = {}


def get_payout_delay_config(tenant_id: str) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    if tid not in _CONFIG_BY_TENANT:
        _CONFIG_BY_TENANT[tid] = {
            "automation_enabled": False,
            "mule_score_hold_threshold": DEFAULT_MULE_SCORE_HOLD_THRESHOLD,
            "janusgraph_property": JANUS_PROPERTY,
            "hold_duration_hours_default": 72,
            "delay_hours_for_action_payout_delay": DEFAULT_DELAY_HOURS,
            "honor_evaluate_action_tags": True,
            "webhook_callback_url": "",
            "mule_candidates": [],
        }
    return dict(_CONFIG_BY_TENANT[tid])


def update_payout_delay_config(
    *,
    tenant_id: str,
    automation_enabled: bool | None = None,
    mule_score_hold_threshold: int | None = None,
    mule_candidates: list[dict[str, Any]] | None = None,
    delay_hours_for_action_payout_delay: int | None = None,
    webhook_callback_url: str | None = None,
    honor_evaluate_action_tags: bool | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    cfg = get_payout_delay_config(tid)
    if automation_enabled is not None:
        cfg["automation_enabled"] = bool(automation_enabled)
    if mule_score_hold_threshold is not None:
        cfg["mule_score_hold_threshold"] = max(1, min(int(mule_score_hold_threshold), 99))
    if mule_candidates is not None:
        cfg["mule_candidates"] = list(mule_candidates)
    if delay_hours_for_action_payout_delay is not None:
        cfg["delay_hours_for_action_payout_delay"] = max(
            1, min(int(delay_hours_for_action_payout_delay), 168)
        )
    if webhook_callback_url is not None:
        cfg["webhook_callback_url"] = str(webhook_callback_url).strip()
    if honor_evaluate_action_tags is not None:
        cfg["honor_evaluate_action_tags"] = bool(honor_evaluate_action_tags)
    _CONFIG_BY_TENANT[tid] = cfg
    return dict(cfg)


async def release_payout_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    payout_id: str,
    released_by: str = "analyst",
) -> dict[str, Any] | None:
    return await release_hold(session, tenant_id, payout_id, released_by=released_by)


def _hold_to_payout_row(hold: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(hold.get("entity_id") or "")
    payout_id = str(hold.get("payout_id") or "")
    amount = hold.get("amount")
    mule = hold.get("mule_score")
    held_at = hold.get("held_at")
    suffix = entity_id[-4:] if len(entity_id) >= 4 else entity_id or "????"

    return {
        "payout_id": payout_id,
        "tenant_id": hold.get("tenant_id") or "demo",
        "entity_id": entity_id,
        "beneficiary_label": f"Beneficiary ·••{suffix}",
        "amount_usd": round(float(amount), 2) if amount is not None else 0.0,
        "currency": hold.get("currency") or "USD",
        "channel": "ach",
        "mule_score": int(mule) if mule is not None else 0,
        "mule_score_source": "janusgraph" if mule is not None else "evaluate",
        "janusgraph_vertex_id": f"v-{entity_id}" if entity_id else "",
        "status": hold.get("status") or "held",
        "hold_reason": hold.get("hold_reason"),
        "held_at": held_at,
        "held_by": hold.get("held_by"),
        "created_at": held_at or _now_iso(),
        "scheduled_release_at": hold.get("scheduled_release_at"),
    }


async def sync_mule_holds_from_candidates(
    session: AsyncSession,
    *,
    tenant_id: str,
    cfg: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    if not cfg.get("automation_enabled", False):
        return 0, []
    if not candidates:
        return 0, []

    threshold = int(cfg.get("mule_score_hold_threshold") or DEFAULT_MULE_SCORE_HOLD_THRESHOLD)
    hours = int(cfg.get("hold_duration_hours_default") or 72)
    existing = await list_holds(session, tenant_id, limit=500)
    by_payout = {h["payout_id"]: h for h in existing}
    writes = 0
    materialized_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        pid = str(candidate.get("payout_id") or "").strip()
        entity_id = str(candidate.get("entity_id") or "").strip()
        if not pid or not entity_id:
            continue

        prior = by_payout.get(pid)
        if prior and prior.get("status") == "released":
            continue
        if prior and prior.get("held_by") == "evaluate":
            continue

        mule = int(candidate.get("mule_score") or 0)
        if mule < threshold:
            continue

        amount = candidate.get("amount")
        if amount is None:
            amount = candidate.get("amount_usd")
        currency = candidate.get("currency") or "USD"

        row, materialized = await upsert_hold(
            session,
            tenant_id=tenant_id,
            payout_id=pid,
            entity_id=entity_id,
            status="held",
            hold_reason=f"janusgraph_{JANUS_PROPERTY}_gte_{threshold}",
            held_by="payout_delay_automation",
            mule_score=float(mule),
            amount=float(amount) if amount is not None else None,
            currency=currency,
            hold_duration_hours=hours,
        )
        if materialized:
            writes += 1
            materialized_rows.append(row)

    return writes, materialized_rows


async def build_payout_delay_payload(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = DEFAULT_PAYOUT_LIMIT,
    http: Any | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(5, min(int(limit), 100))
    cfg = get_payout_delay_config(tid)

    candidates = cfg.get("mule_candidates") or []
    automation_writes = 0
    if cfg.get("automation_enabled") and candidates:
        automation_writes, materialized_rows = await sync_mule_holds_from_candidates(
            session, tenant_id=tid, cfg=cfg, candidates=candidates
        )
        callback_url = str(cfg.get("webhook_callback_url") or "").strip()
        if http is not None and callback_url and materialized_rows:
            from integration_ingress.marketplace_webhook_logs import (
                SIGNAL_PAYOUT_HOLD,
                notify_payout_signal_webhook,
            )

            for hold_row in materialized_rows:
                await notify_payout_signal_webhook(
                    session,
                    http,
                    signal=SIGNAL_PAYOUT_HOLD,
                    callback_url=callback_url,
                    hold_row=hold_row,
                )

    holds = await list_holds(session, tid, limit=lim)
    payouts = [_hold_to_payout_row(h) for h in holds]
    payouts_sorted = sorted(
        payouts,
        key=lambda p: (
            0 if p["status"] == "held" else 1 if p["status"] == "pending" else 2,
            -int(p.get("mule_score") or 0),
            str(p["payout_id"]),
        ),
    )

    held = [p for p in payouts if p["status"] == "held"]
    released = [p for p in payouts if p["status"] == "released"]
    threshold = int(cfg["mule_score_hold_threshold"])

    events: list[dict[str, Any]] = []
    for p in held[:8]:
        events.append(
            {
                "event_id": f"evt_hold_{p['payout_id'][-8:]}",
                "event_type": "automation_hold",
                "payout_id": p["payout_id"],
                "mule_score": p["mule_score"],
                "threshold": threshold,
                "timestamp": p.get("held_at") or _now_iso(),
                "detail": (
                    f"JanusGraph {JANUS_PROPERTY}={p['mule_score']} ≥ {threshold}"
                    if p.get("held_by") == "payout_delay_automation"
                    else (p.get("hold_reason") or "payout hold")
                ),
            },
        )

    has_automation_holds = any(
        h.get("held_by") == "payout_delay_automation" for h in holds
    )
    source = (
        "durable+automation"
        if automation_writes > 0 or has_automation_holds
        else "durable"
    )

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": source,
        "config": cfg,
        "summary": {
            "pending_count": sum(1 for p in payouts if p["status"] == "pending"),
            "held_count": len(held),
            "released_count": len(released),
            "held_amount_usd": round(sum(float(p["amount_usd"]) for p in held), 2),
            "automation_active": bool(cfg.get("automation_enabled")),
        },
        "events": events,
        "payouts": payouts_sorted,
    }
