#!/usr/bin/env python3
"""P2: named marketplace demo tenant proof (durable boards + collusion + measured FPR).

Tenant: mkt-demo-2026
Not a live L3 ops ledger. Does not forge LIVE partner pins.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "marketplace_demo_tenant_labels.json"
TENANT_ID = "mkt-demo-2026"


def compute_hold_fpr(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """False positive rate among predicted holds: hold & legit / all holds."""
    predicted = [r for r in rows if r.get("predicted_hold")]
    if not predicted:
        return {
            "false_positive_rate": None,
            "holds": 0,
            "false_positives": 0,
            "true_positives": 0,
            "ok": False,
            "reason": "no_predicted_holds",
        }
    fp = sum(1 for r in predicted if str(r.get("y_label")) == "0")
    tp = sum(1 for r in predicted if str(r.get("y_label")) == "1")
    fpr = fp / len(predicted)
    return {
        "false_positive_rate": round(fpr, 4),
        "holds": len(predicted),
        "false_positives": fp,
        "true_positives": tp,
        "ok": True,
        "reason": "ok",
    }


def prove_collusion_roles() -> dict[str, Any]:
    sys.path.insert(0, str(_REPO / "services" / "case-api" / "src"))
    from case_api.multi_party_links import map_labels_to_roles

    checks = [
        (["Seller", "Device"], "seller"),
        (["Courier", "Driver"], "courier"),
        (["Buyer", "Customer"], "buyer"),
    ]
    roles_ok = True
    samples: list[dict[str, Any]] = []
    for labels, expect in checks:
        mapped = map_labels_to_roles(labels)
        hit = expect in mapped
        roles_ok = roles_ok and hit
        samples.append({"labels": labels, "roles": mapped, "expect": expect, "ok": hit})
    # Synthetic rail row shape (API contract, not invented client roles)
    rail = {
        "case_id": "demo-case",
        "entity_id": "seller-ring-a",
        "tenant_id": TENANT_ID,
        "degraded": False,
        "links": [
            {
                "entity_id": "courier-mule-1",
                "roles": map_labels_to_roles(["Courier"]),
                "propagated_risk_score": 55.0,
                "shared_signals": ["shared_device"],
                "path_description": "(seller-ring-a)-[SHARED_DEVICE]->(courier-mule-1)",
            }
        ],
    }
    return {
        "ok": roles_ok and bool(rail["links"][0]["roles"]),
        "role_samples": samples,
        "rail_sample": rail,
    }


async def seed_durable_boards() -> dict[str, Any]:
    sys.path.insert(0, str(_REPO / "services" / "integration-ingress" / "src"))
    from integration_ingress.db import Base
    from integration_ingress.payout_delay_automation import build_payout_delay_payload
    from integration_ingress.payout_hold_store import upsert_hold
    from integration_ingress.promo_abuse_store import upsert_redemption
    from integration_ingress.promo_abuse_tracking import build_promo_abuse_payload
    from integration_ingress.seller_integrity import build_seller_integrity_payload
    from integration_ingress.seller_integrity_store import upsert_seller
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # noqa: F401 — register models on Base.metadata
    from integration_ingress import models as _models  # noqa: F401

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "mkt_demo.db"
        eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await upsert_hold(
                session,
                tenant_id=TENANT_ID,
                payout_id="po_mkt_demo_1",
                entity_id="seller-ring-a",
                status="held",
                hold_reason="risk:collusion_shared_device",
                held_by="marketplace_demo_tenant_proof",
                tags=["action:payout_hold", "risk:collusion_shared_device"],
                amount=1250.0,
                currency="USD",
                mule_score=82,
            )
            await upsert_hold(
                session,
                tenant_id=TENANT_ID,
                payout_id="po_mkt_demo_2",
                entity_id="seller-ring-b",
                status="held",
                hold_reason="action:payout_delay",
                held_by="marketplace_demo_tenant_proof",
                tags=["action:payout_delay"],
                amount=400.0,
                currency="USD",
                mule_score=61,
            )
            await upsert_redemption(
                session,
                tenant_id=TENANT_ID,
                coupon_code="WELCOME50",
                user_id="buyer-farm-1",
                device_id="dev-shared-1",
                order_total=49.0,
                currency="USD",
                flags=["risk:promo_farm"],
                trace_id="md-promo-1",
            )
            await upsert_redemption(
                session,
                tenant_id=TENANT_ID,
                coupon_code="WELCOME50",
                user_id="buyer-farm-2",
                device_id="dev-shared-1",
                order_total=51.0,
                currency="USD",
                flags=["risk:promo_farm"],
                trace_id="md-promo-2",
            )
            await upsert_seller(
                session,
                tenant_id=TENANT_ID,
                seller_id="seller-ring-a",
                successful_deliveries=12,
                review_count=40,
            )
            await upsert_seller(
                session,
                tenant_id=TENANT_ID,
                seller_id="seller-clean-1",
                successful_deliveries=200,
                review_count=70,
            )
            await session.commit()

            payout = await build_payout_delay_payload(
                session, tenant_id=TENANT_ID, limit=25
            )
            promo = await build_promo_abuse_payload(
                session, tenant_id=TENANT_ID, coupon_code="WELCOME50", window_days=30
            )
            seller = await build_seller_integrity_payload(
                session, tenant_id=TENANT_ID, limit=25
            )
        await eng.dispose()

    payout_n = len(payout.get("payouts") or [])
    promo_summary = promo.get("summary") if isinstance(promo.get("summary"), dict) else {}
    promo_ok = promo.get("source") == "durable" and int(
        promo_summary.get("total_redemptions") or 0
    ) >= 2
    seller_n = len(seller.get("sellers") or [])
    return {
        "tenant_id": TENANT_ID,
        "payout": {
            "source": payout.get("source"),
            "count": payout_n,
            "ok": payout.get("source") == "durable" and payout_n >= 2,
        },
        "promo": {
            "source": promo.get("source"),
            "ok": promo_ok,
            "summary": promo.get("summary"),
        },
        "seller": {
            "source": seller.get("source"),
            "count": seller_n,
            "ok": seller.get("source") == "durable" and seller_n >= 2,
        },
    }


async def run_proof() -> dict[str, Any]:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert raw.get("tenant_id") == TENANT_ID
    fpr = compute_hold_fpr(list(raw.get("rows") or []))
    collusion = prove_collusion_roles()
    boards = await seed_durable_boards()

    # Grounded bar: boards non-empty durable + collusion roles + measurable FPR ≤ 0.25
    fpr_val = fpr.get("false_positive_rate")
    fpr_ok = fpr.get("ok") and fpr_val is not None and float(fpr_val) <= 0.25
    ok = (
        bool(boards["payout"]["ok"])
        and bool(boards["promo"]["ok"])
        and bool(boards["seller"]["ok"])
        and bool(collusion["ok"])
        and bool(fpr_ok)
    )
    return {
        "schema_id": "tarka.marketplace_demo_tenant_proof/v1",
        "tenant_id": TENANT_ID,
        "ok": ok,
        "boards": boards,
        "collusion": {"ok": collusion["ok"], "role_samples": collusion["role_samples"]},
        "false_positive": fpr,
        "honesty": (
            "Named demo tenant fixture proof — not a live production tenant outcome pack. "
            "L3 ops ledger remains NOT STARTED. L2 partner fusion remains WAIVED without vendor pins."
        ),
    }


def main() -> int:
    out = asyncio.run(run_proof())
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
