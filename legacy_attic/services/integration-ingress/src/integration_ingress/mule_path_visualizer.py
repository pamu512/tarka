"""Mule path visualizer — User A → User B (mule) → Payout fund flow (Prompt 179)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

HopRole = Literal["origin", "mule", "payout"]

_DEMO_PATHS: dict[str, dict[str, Any]] = {
    "default": {
        "origin": {"entity_id": "user_alice", "label": "Alice Johnson", "account_id": "acc_alice_main"},
        "mule": {
            "entity_id": "mule_ivan",
            "label": "Ivan Kowalski",
            "account_id": "acc_mule_ivan_recv",
            "referred_by": "fraud_frank",
        },
        "payout": {
            "entity_id": "payout_crypto_eu",
            "label": "External payout (crypto)",
            "beneficiary": "bc1q…mule-cashout",
            "channel": "crypto_withdrawal",
        },
        "leg1_amount": 12_400.0,
        "leg2_amount": 11_950.0,
        "currency": "USD",
        "hours_span": 4.2,
    },
    "fraud_frank_chain": {
        "origin": {"entity_id": "fraud_frank", "label": "Frank Moretti", "account_id": "acc_frank_burner"},
        "mule": {
            "entity_id": "mule_jane",
            "label": "Jane Okafor",
            "account_id": "acc_mule_jane_recv",
            "referred_by": "fraud_gina",
        },
        "payout": {
            "entity_id": "payout_wire_offshore",
            "label": "Offshore wire beneficiary",
            "beneficiary": "LT71 3250 …4821",
            "channel": "international_wire",
        },
        "leg1_amount": 8_750.0,
        "leg2_amount": 8_500.0,
        "currency": "USD",
        "hours_span": 2.8,
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _path_key(tenant_id: str, origin: str, mule: str, payout: str) -> str:
    raw = f"{tenant_id}|{origin}|{mule}|{payout}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _resolve_demo_template(
    *,
    origin_entity_id: str | None,
    mule_entity_id: str | None,
) -> dict[str, Any]:
    if origin_entity_id == "fraud_frank" or mule_entity_id == "mule_jane":
        return _DEMO_PATHS["fraud_frank_chain"]
    return _DEMO_PATHS["default"]


def _hop(
    *,
    role: HopRole,
    entity_id: str,
    label: str,
    node_type: str,
    account_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "role": role,
        "entity_id": entity_id,
        "label": label,
        "node_type": node_type,
        "account_id": account_id,
    }
    if extra:
        row.update(extra)
    return row


def build_mule_path_payload(
    *,
    tenant_id: str,
    origin_entity_id: str | None = None,
    mule_entity_id: str | None = None,
    payout_entity_id: str | None = None,
) -> dict[str, Any]:
    """Build a three-hop mule fund-flow path (demo templates + optional entity overrides)."""
    tid = (tenant_id or "demo").strip() or "demo"
    tpl = _resolve_demo_template(origin_entity_id=origin_entity_id, mule_entity_id=mule_entity_id)

    origin = dict(tpl["origin"])
    mule = dict(tpl["mule"])
    payout = dict(tpl["payout"])
    if origin_entity_id:
        origin["entity_id"] = origin_entity_id.strip()
    if mule_entity_id:
        mule["entity_id"] = mule_entity_id.strip()
    if payout_entity_id:
        payout["entity_id"] = payout_entity_id.strip()

    currency = str(tpl.get("currency") or "USD")
    leg1 = float(tpl["leg1_amount"])
    leg2 = float(tpl["leg2_amount"])
    hours = float(tpl.get("hours_span") or 3.0)
    t_end = datetime.now(UTC)
    t_mid = t_end - timedelta(hours=hours * 0.45)
    t_start = t_end - timedelta(hours=hours)

    trace1 = f"tr-mule-{uuid.uuid4().hex[:10]}"
    trace2 = f"tr-mule-{uuid.uuid4().hex[:10]}"

    hops = [
        _hop(
            role="origin",
            entity_id=str(origin["entity_id"]),
            label=str(origin.get("label") or origin["entity_id"]),
            node_type="user",
            account_id=origin.get("account_id"),
            extra={"description": "Source account — funds leave here"},
        ),
        _hop(
            role="mule",
            entity_id=str(mule["entity_id"]),
            label=str(mule.get("label") or mule["entity_id"]),
            node_type="user",
            account_id=mule.get("account_id"),
            extra={
                "description": "Pass-through / mule account",
                "referred_by": mule.get("referred_by"),
                "tags": ["mule", "layering"],
            },
        ),
        _hop(
            role="payout",
            entity_id=str(payout["entity_id"]),
            label=str(payout.get("label") or payout["entity_id"]),
            node_type="payout",
            extra={
                "description": "Cash-out / external beneficiary",
                "beneficiary": payout.get("beneficiary"),
                "channel": payout.get("channel"),
            },
        ),
    ]

    transfers = [
        {
            "id": f"xfer-{trace1}",
            "from_role": "origin",
            "to_role": "mule",
            "from_entity_id": hops[0]["entity_id"],
            "to_entity_id": hops[1]["entity_id"],
            "amount": leg1,
            "currency": currency,
            "trace_id": trace1,
            "timestamp": t_start.isoformat(),
            "channel": "internal_transfer",
            "status": "settled",
        },
        {
            "id": f"xfer-{trace2}",
            "from_role": "mule",
            "to_role": "payout",
            "from_entity_id": hops[1]["entity_id"],
            "to_entity_id": hops[2]["entity_id"],
            "amount": leg2,
            "currency": currency,
            "trace_id": trace2,
            "timestamp": t_mid.isoformat(),
            "channel": str(payout.get("channel") or "payout"),
            "status": "settled",
        },
    ]

    retained = round(leg1 - leg2, 2)
    pid = _path_key(tid, hops[0]["entity_id"], hops[1]["entity_id"], hops[2]["entity_id"])

    return {
        "tenant_id": tid,
        "path_id": pid,
        "updated_at": _now_iso(),
        "source": "demo_template",
        "hops": hops,
        "transfers": transfers,
        "summary": {
            "hop_count": len(hops),
            "total_outflow": leg1,
            "payout_amount": leg2,
            "mule_retained": max(0.0, retained),
            "currency": currency,
            "elapsed_hours": round(hours, 2),
            "risk_flags": [
                "rapid_pass_through",
                "mule_account",
                "external_payout",
                *(["known_fraud_referrer"] if mule.get("referred_by") else []),
            ],
        },
    }
