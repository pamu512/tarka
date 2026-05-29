"""Payout delay automation — hold funds when JanusGraph mule_score is high (Prompt 183)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_MULE_SCORE_HOLD_THRESHOLD = 72
DEFAULT_PAYOUT_LIMIT = 35
JANUS_PROPERTY = "mule_score"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_CONFIG_BY_TENANT: dict[str, dict[str, Any]] = {}
_RELEASED_PAYOUT_IDS: set[str] = set()


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


def release_payout_hold(*, tenant_id: str, payout_id: str) -> dict[str, Any] | None:
    tid = (tenant_id or "demo").strip() or "demo"
    key = f"{tid}:{payout_id.strip()}"
    _RELEASED_PAYOUT_IDS.add(key)
    return {
        "tenant_id": tid,
        "payout_id": payout_id,
        "released_at": _now_iso(),
        "released_by": "analyst",
    }


def _payout_row(index: int, *, tenant_id: str) -> dict[str, Any]:
    seed = hashlib.sha256(f"{tenant_id}:payout_delay:{index}".encode()).hexdigest()
    bucket = int(seed[0:3], 16) % 11
    mule_score = min(99, 28 + bucket * 7 + (int(seed[3:5], 16) % 18))
    amount = 1200 + (int(seed[5:9], 16) % 48000)
    payout_id = f"payout_{seed[:12]}"
    entity_id = f"ent_{seed[12:20]}"
    created = datetime.now(UTC) - timedelta(minutes=index * 17 + 4)

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
        "status": "pending",
        "hold_reason": None,
        "held_at": None,
        "held_by": None,
        "created_at": created.isoformat(),
        "scheduled_release_at": None,
    }


def _apply_automation(
    payout: dict[str, Any], cfg: dict[str, Any], *, tenant_id: str
) -> dict[str, Any]:
    tid = tenant_id
    pid = str(payout["payout_id"])
    release_key = f"{tid}:{pid}"
    row = dict(payout)

    if release_key in _RELEASED_PAYOUT_IDS:
        row["status"] = "released"
        row["hold_reason"] = None
        row["held_by"] = None
        return row

    threshold = int(cfg.get("mule_score_hold_threshold") or DEFAULT_MULE_SCORE_HOLD_THRESHOLD)
    mule = int(row.get("mule_score") or 0)
    enabled = bool(cfg.get("automation_enabled", True))

    if enabled and mule >= threshold:
        held_at = datetime.now(UTC) - timedelta(minutes=3)
        hours = int(cfg.get("hold_duration_hours_default") or 72)
        row["status"] = "held"
        row["hold_reason"] = f"janusgraph_{JANUS_PROPERTY}_gte_{threshold}"
        row["held_at"] = held_at.isoformat()
        row["held_by"] = "payout_delay_automation"
        row["scheduled_release_at"] = (held_at + timedelta(hours=hours)).isoformat()
    return row


def build_payout_delay_payload(
    *,
    tenant_id: str,
    limit: int = DEFAULT_PAYOUT_LIMIT,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(5, min(int(limit), 100))
    cfg = get_payout_delay_config(tid)

    raw = [_payout_row(i, tenant_id=tid) for i in range(lim)]
    payouts = [_apply_automation(p, cfg, tenant_id=tid) for p in raw]
    payouts_sorted = sorted(
        payouts,
        key=lambda p: (
            0 if p["status"] == "held" else 1,
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
                "detail": f"JanusGraph {JANUS_PROPERTY}={p['mule_score']} ≥ {threshold}",
            },
        )

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
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
