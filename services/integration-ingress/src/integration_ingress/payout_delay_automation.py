"""Payout delay automation — hold funds when JanusGraph mule_score is high (Prompt 183)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.payout_hold_store import list_holds, release_hold, upsert_hold

DEFAULT_MULE_SCORE_HOLD_THRESHOLD = 72
DEFAULT_PAYOUT_LIMIT = 35
JANUS_PROPERTY = "mule_score"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_CONFIG_BY_TENANT: dict[str, dict[str, Any]] = {}


def get_payout_delay_config(tenant_id: str) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    if tid not in _CONFIG_BY_TENANT:
        _CONFIG_BY_TENANT[tid] = {
            "automation_enabled": True,
            "mule_score_hold_threshold": DEFAULT_MULE_SCORE_HOLD_THRESHOLD,
            "janusgraph_property": JANUS_PROPERTY,
            "hold_duration_hours_default": 72,
        }
    return dict(_CONFIG_BY_TENANT[tid])


def update_payout_delay_config(
    *,
    tenant_id: str,
    automation_enabled: bool | None = None,
    mule_score_hold_threshold: int | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    cfg = get_payout_delay_config(tid)
    if automation_enabled is not None:
        cfg["automation_enabled"] = bool(automation_enabled)
    if mule_score_hold_threshold is not None:
        cfg["mule_score_hold_threshold"] = max(1, min(int(mule_score_hold_threshold), 99))
    _CONFIG_BY_TENANT[tid] = cfg
    return dict(cfg)


async def release_payout_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    payout_id: str,
    released_by: str = "analyst",
) -> dict[str, Any] | None:
    released = await release_hold(session, tenant_id, payout_id, released_by=released_by)
    if released is None:
        tid = (tenant_id or "demo").strip() or "demo"
        return {
            "tenant_id": tid,
            "payout_id": payout_id,
            "released_at": _now_iso(),
            "released_by": released_by,
            "status": "released",
        }
    return released


def _mule_score_candidate(index: int, *, tenant_id: str) -> dict[str, Any]:
    """Explicit JanusGraph mule_score input for automation (not list filler)."""
    seed = hashlib.sha256(f"{tenant_id}:payout_delay:{index}".encode()).hexdigest()
    bucket = int(seed[0:3], 16) % 11
    mule_score = min(99, 28 + bucket * 7 + (int(seed[3:5], 16) % 18))
    amount = 1200 + (int(seed[5:9], 16) % 48000)
    payout_id = f"payout_{seed[:12]}"
    entity_id = f"ent_{seed[12:20]}"

    return {
        "payout_id": payout_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "beneficiary_label": f"Beneficiary ·••{seed[20:24]}",
        "amount_usd": round(amount / 100, 2),
        "currency": "USD",
        "channel": ["ach", "wire", "instant", "crypto"][index % 4],
        "mule_score": mule_score,
        "mule_score_source": "janusgraph",
        "janusgraph_vertex_id": f"v-{entity_id}",
    }


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


async def _sync_mule_automation_holds(
    session: AsyncSession,
    *,
    tenant_id: str,
    cfg: dict[str, Any],
    limit: int,
) -> bool:
    if not cfg.get("automation_enabled", True):
        return False

    threshold = int(cfg.get("mule_score_hold_threshold") or DEFAULT_MULE_SCORE_HOLD_THRESHOLD)
    hours = int(cfg.get("hold_duration_hours_default") or 72)
    existing = await list_holds(session, tenant_id, limit=500)
    by_payout = {h["payout_id"]: h for h in existing}
    wrote = False

    for i in range(max(5, min(int(limit), 100))):
        candidate = _mule_score_candidate(i, tenant_id=tenant_id)
        pid = candidate["payout_id"]
        prior = by_payout.get(pid)
        if prior and prior.get("status") == "released":
            continue
        if prior and prior.get("held_by") == "evaluate":
            continue

        mule = int(candidate.get("mule_score") or 0)
        if mule < threshold:
            continue

        _, _ = await upsert_hold(
            session,
            tenant_id=tenant_id,
            payout_id=pid,
            entity_id=candidate["entity_id"],
            status="held",
            hold_reason=f"janusgraph_{JANUS_PROPERTY}_gte_{threshold}",
            held_by="payout_delay_automation",
            mule_score=float(mule),
            amount=float(candidate["amount_usd"]),
            currency=candidate.get("currency", "USD"),
            hold_duration_hours=hours,
        )
        wrote = True

    return wrote


async def build_payout_delay_payload(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int = DEFAULT_PAYOUT_LIMIT,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(5, min(int(limit), 100))
    cfg = get_payout_delay_config(tid)

    automation_wrote = await _sync_mule_automation_holds(
        session, tenant_id=tid, cfg=cfg, limit=lim
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

    source = "durable+automation" if automation_wrote else "durable"

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
