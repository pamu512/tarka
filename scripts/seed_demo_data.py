#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import httpx

"""
Seed realistic demo data into the Tarka APIs.

Usage:
    pip install -r scripts/requirements.txt
    python scripts/seed_demo_data.py

    # Custom API URLs:
    python scripts/seed_demo_data.py \
        --decision-url http://localhost:8000 \
        --case-url http://localhost:8002 \
        --graph-url http://localhost:8001
"""
TENANT_ID = "demo"

# ---------------------------------------------------------------------------
# Entity definitions
# ---------------------------------------------------------------------------

LEGIT_USERS = [
    {"id": "user_alice", "name": "Alice Johnson", "email": "alice@example.com"},
    {"id": "user_bob", "name": "Bob Smith", "email": "bob@example.com"},
    {"id": "user_carol", "name": "Carol White", "email": "carol@example.com"},
    {"id": "user_diana", "name": "Diana Chen", "email": "diana@example.com"},
    {"id": "user_evan", "name": "Evan Brown", "email": "evan@example.com"},
]

FRAUDSTERS = [
    {"id": "fraud_frank", "name": "Frank Moretti", "role": "ring_leader"},
    {"id": "fraud_gina", "name": "Gina Petrova", "role": "device_specialist"},
    {"id": "fraud_henry", "name": "Henry Tanaka", "role": "social_engineer"},
]

MULES = [
    {"id": "mule_ivan", "name": "Ivan Kowalski", "referred_by": "fraud_frank"},
    {"id": "mule_jane", "name": "Jane Okafor", "referred_by": "fraud_gina"},
]

DEVICES = [
    {"id": "dev_laptop_001", "platform": "web", "owner": "user_alice", "signals": {}},
    {"id": "dev_phone_002", "platform": "ios", "owner": "user_bob", "signals": {}},
    {
        "id": "dev_emulator_003",
        "platform": "android",
        "owner": "fraud_frank",
        "shared_with": ["fraud_gina"],
        "signals": {"is_emulator": True, "is_vpn": True, "automation_detected": True},
    },
    {
        "id": "dev_vpn_004",
        "platform": "web",
        "owner": "fraud_frank",
        "shared_with": ["fraud_henry"],
        "signals": {"is_vpn": True, "ip_is_datacenter": True, "timezone_geo_mismatch": True},
    },
    {"id": "dev_phone_005", "platform": "ios", "owner": "user_carol", "signals": {}},
]

ACCOUNTS = [
    {"id": "acc_alice_main", "owner": "user_alice", "type": "checking"},
    {"id": "acc_bob_checking", "owner": "user_bob", "type": "checking"},
    {"id": "acc_frank_burner", "owner": "fraud_frank", "type": "prepaid"},
    {"id": "acc_gina_prepaid", "owner": "fraud_gina", "type": "prepaid"},
    {"id": "acc_mule_ivan_recv", "owner": "mule_ivan", "type": "savings"},
]

# ---------------------------------------------------------------------------
# Transaction templates
# ---------------------------------------------------------------------------


def _ts(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def _legit_transactions() -> list[dict]:
    """Normal transactions from legitimate users."""
    txns: list[dict] = []
    random.seed(42)

    for user in LEGIT_USERS:
        device = next(
            (d for d in DEVICES if d.get("owner") == user["id"]),
            DEVICES[0],
        )
        count = random.randint(4, 7)
        for i in range(count):
            txns.append(
                {
                    "tenant_id": TENANT_ID,
                    "event_type": "payment",
                    "entity_id": user["id"],
                    "session_id": f"sess_{user['id']}_{i}",
                    "payload": {
                        "amount": round(random.uniform(5, 150), 2),
                        "currency": "USD",
                        "merchant": random.choice(
                            [
                                "Amazon",
                                "Target",
                                "Starbucks",
                                "Uber",
                                "Netflix",
                                "Spotify",
                                "Walmart",
                                "DoorDash",
                            ]
                        ),
                        "ip_address": f"73.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                        "timestamp": _ts(random.uniform(1, 720)),
                    },
                    "device_context": {
                        "device_id": device["id"],
                        "platform": device["platform"],
                        "signals": device.get("signals", {}),
                    },
                    "metadata": {"source": "demo_seed", "category": "legit"},
                }
            )
    return txns


def _fraudster_transactions() -> list[dict]:
    """Suspicious transactions from fraudsters — high amounts, bad signals."""
    txns: list[dict] = []
    random.seed(99)

    device_map = {
        "fraud_frank": "dev_emulator_003",
        "fraud_gina": "dev_emulator_003",
        "fraud_henry": "dev_vpn_004",
    }
    for fraudster in FRAUDSTERS:
        dev_id = device_map[fraudster["id"]]
        device = next(d for d in DEVICES if d["id"] == dev_id)
        for i in range(5):
            txns.append(
                {
                    "tenant_id": TENANT_ID,
                    "event_type": "payment",
                    "entity_id": fraudster["id"],
                    "session_id": f"sess_{fraudster['id']}_{i}",
                    "payload": {
                        "amount": round(random.uniform(500, 5000), 2),
                        "currency": "USD",
                        "merchant": random.choice(
                            [
                                "CryptoExchange",
                                "WireTransfer",
                                "GiftCardMall",
                                "ElectronicsWholesale",
                                "PreciousMetals",
                            ]
                        ),
                        "ip_address": f"185.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                        "timestamp": _ts(random.uniform(0.5, 48)),
                    },
                    "device_context": {
                        "device_id": device["id"],
                        "platform": device["platform"],
                        "signals": device.get("signals", {}),
                    },
                    "metadata": {"source": "demo_seed", "category": "fraud"},
                }
            )
    return txns


def _velocity_spike_transactions() -> list[dict]:
    """Rapid-fire transactions from Frank within a 2-minute window."""
    txns: list[dict] = []
    base_time = datetime.now(UTC) - timedelta(hours=2)
    device = next(d for d in DEVICES if d["id"] == "dev_emulator_003")

    for i in range(8):
        ts = base_time + timedelta(seconds=i * 15)
        txns.append(
            {
                "tenant_id": TENANT_ID,
                "event_type": "payment",
                "entity_id": "fraud_frank",
                "session_id": f"sess_velocity_{i}",
                "payload": {
                    "amount": round(random.uniform(200, 800), 2),
                    "currency": "USD",
                    "merchant": "CryptoExchange",
                    "ip_address": "185.220.101.42",
                    "timestamp": ts.isoformat(),
                },
                "device_context": {
                    "device_id": device["id"],
                    "platform": device["platform"],
                    "signals": device.get("signals", {}),
                },
                "metadata": {"source": "demo_seed", "category": "velocity_spike"},
            }
        )
    return txns


def _mule_transactions() -> list[dict]:
    """Sender evaluate: fraudster pays the mule. Graph edge comes from counterparty_entity_id."""
    txns: list[dict] = []
    random.seed(184)
    for mule in MULES:
        sender = mule["referred_by"]
        for i in range(3):
            txns.append(
                {
                    "tenant_id": TENANT_ID,
                    "event_type": "payment",
                    "entity_id": sender,
                    "session_id": f"sess_{sender}_to_{mule['id']}_{i}",
                    "payload": {
                        "amount": round(random.uniform(1000, 3000), 2),
                        "currency": "USD",
                        "merchant": "WireTransfer",
                        "counterparty_entity_id": mule["id"],
                        "ip_address": f"45.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                        "timestamp": _ts(random.uniform(1, 24)),
                    },
                    "metadata": {
                        "source": "demo_seed",
                        "category": "mule_transfer",
                        "referred_by": mule["referred_by"],
                    },
                }
            )
    return txns


def _login_transactions() -> list[dict]:
    """Login events from both legit and suspicious entities."""
    txns: list[dict] = []
    for user in LEGIT_USERS[:3]:
        device = next(
            (d for d in DEVICES if d.get("owner") == user["id"]),
            DEVICES[0],
        )
        txns.append(
            {
                "tenant_id": TENANT_ID,
                "event_type": "login",
                "entity_id": user["id"],
                "payload": {
                    "ip_address": f"73.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                    "timestamp": _ts(random.uniform(0.1, 12)),
                },
                "device_context": {
                    "device_id": device["id"],
                    "platform": device["platform"],
                    "signals": device.get("signals", {}),
                },
                "metadata": {"source": "demo_seed"},
            }
        )

    for fraudster in FRAUDSTERS:
        dev_id = "dev_emulator_003" if fraudster["id"] != "fraud_henry" else "dev_vpn_004"
        device = next(d for d in DEVICES if d["id"] == dev_id)
        txns.append(
            {
                "tenant_id": TENANT_ID,
                "event_type": "login",
                "entity_id": fraudster["id"],
                "payload": {
                    "ip_address": f"185.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}",
                    "timestamp": _ts(random.uniform(0.1, 6)),
                },
                "device_context": {
                    "device_id": device["id"],
                    "platform": device["platform"],
                    "signals": device.get("signals", {}),
                },
                "metadata": {"source": "demo_seed"},
            }
        )
    return txns


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------

CASES = [
    {
        "tenant_id": TENANT_ID,
        "title": "Velocity spike — fraud_frank (8 txns in 2 min)",
        "entity_id": "fraud_frank",
        "priority": "high",
        "target_status": "open",
        "labels": ["velocity", "fraud_ring", "high_amount"],
        "comments": [
            {
                "author": "system",
                "body": "Auto-created: 8 transactions detected within a 2-minute window totalling $3,400+.",
            },
            {
                "author": "analyst_maria",
                "body": "Confirmed emulator usage with VPN. Escalating to fraud ring investigation.",
            },
        ],
    },
    {
        "tenant_id": TENANT_ID,
        "title": "Shared device fraud ring — dev_emulator_003",
        "entity_id": "fraud_gina",
        "priority": "critical",
        "target_status": "open",
        "labels": ["shared_device", "emulator", "fraud_ring"],
        "comments": [
            {
                "author": "system",
                "body": "Auto-created: Device dev_emulator_003 shared by fraud_frank and fraud_gina.",
            },
            {
                "author": "analyst_james",
                "body": "Same device fingerprint across two supposedly unrelated accounts. Classic ring pattern.",
            },
            {
                "author": "analyst_maria",
                "body": "Linked to velocity case on fraud_frank. Recommending coordinated takedown.",
            },
        ],
    },
    {
        "tenant_id": TENANT_ID,
        "title": "Account takeover attempt — user_bob",
        "entity_id": "user_bob",
        "priority": "high",
        "target_status": "investigating",
        "labels": ["ato", "vpn", "geo_mismatch"],
        "comments": [
            {
                "author": "system",
                "body": "Login from new device with VPN detected. Geo-IP mismatch with known location.",
            },
            {
                "author": "analyst_james",
                "body": "Contacted customer — confirms they did NOT log in. Resetting credentials.",
            },
        ],
    },
    {
        "tenant_id": TENANT_ID,
        "title": "Confirmed fraud — fraud_henry wire transfers",
        "entity_id": "fraud_henry",
        "priority": "medium",
        "target_status": "resolved",
        "labels": ["confirmed_fraud", "wire_transfer", "social_engineering"],
        "comments": [
            {"author": "system", "body": "Multiple high-value wire transfers from VPN-masked IP."},
            {
                "author": "analyst_maria",
                "body": "Traced to social engineering ring. Account frozen. SAR filed.",
            },
            {
                "author": "analyst_james",
                "body": "Resolution: Account permanently blocked. Funds recovered: $12,400.",
            },
        ],
    },
    {
        "tenant_id": TENANT_ID,
        "title": "False positive — user_carol large purchase",
        "entity_id": "user_carol",
        "priority": "low",
        "target_status": "closed",
        "labels": ["false_positive", "high_amount"],
        "comments": [
            {
                "author": "system",
                "body": "Flagged: $1,200 purchase at ElectronicsStore — unusual for this customer.",
            },
            {
                "author": "analyst_james",
                "body": "Customer confirmed purchase (new laptop). Closing as false positive.",
            },
        ],
    },
    {
        "tenant_id": TENANT_ID,
        "title": "Mule network — mule_ivan receiving funds",
        "entity_id": "mule_ivan",
        "priority": "high",
        "target_status": "open",
        "labels": ["mule", "wire_transfer", "fraud_ring"],
        "comments": [
            {
                "author": "system",
                "body": "Multiple incoming transfers from fraud_frank flagged account.",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------


async def _already_seeded(client: httpx.AsyncClient, case_url: str) -> bool:
    try:
        r = await client.get(
            f"{case_url}/v1/cases",
            params={"tenant_id": TENANT_ID, "limit": 1},
        )
        if r.status_code == 200:
            items = r.json().get("items", [])
            return len(items) > 0
    except httpx.HTTPError:
        pass
    return False


def require_seed_planes(*, decision_ok: bool, graph_ok: bool) -> None:
    if not decision_ok:
        print("Aborting — decision-api must be running.", file=sys.stderr)
        raise SystemExit(1)
    if not graph_ok:
        print("Aborting — graph-service must be running.", file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def seed_decisions(client: httpx.AsyncClient, decision_url: str) -> list[str]:
    """Send evaluate requests and collect trace_ids."""
    all_txns = (
        _legit_transactions()
        + _fraudster_transactions()
        + _velocity_spike_transactions()
        + _mule_transactions()
        + _login_transactions()
    )
    print(f"  Sending {len(all_txns)} decision evaluations ...")
    trace_ids: list[str] = []
    ok = 0
    errors = 0

    for i, txn in enumerate(all_txns, 1):
        try:
            r = await client.post(f"{decision_url}/v1/decisions/evaluate", json=txn)
            if r.status_code == 200:
                trace_ids.append(r.json().get("trace_id", ""))
                ok += 1
            else:
                errors += 1
        except httpx.HTTPError:
            errors += 1

        if i % 10 == 0 or i == len(all_txns):
            print(f"    [{i}/{len(all_txns)}] ok={ok} errors={errors}")

    return trace_ids


async def seed_cases(client: httpx.AsyncClient, case_url: str, trace_ids: list[str]) -> None:
    """Create cases with comments, labels, and status transitions."""
    print(f"  Creating {len(CASES)} investigation cases ...")

    for idx, case_def in enumerate(CASES):
        trace = trace_ids[idx] if idx < len(trace_ids) else str(uuid.uuid4())

        create_body = {
            "tenant_id": case_def["tenant_id"],
            "title": case_def["title"],
            "entity_id": case_def["entity_id"],
            "trace_id": trace,
            "priority": case_def["priority"],
        }
        try:
            r = await client.post(f"{case_url}/v1/cases", json=create_body)
            if r.status_code not in (200, 201):
                print(f"    WARN: case create returned {r.status_code}")
                continue
            case_data = r.json()
            case_id = case_data["id"]
        except httpx.HTTPError as exc:
            print(f"    WARN: case create failed: {exc}")
            continue

        tid = case_def["tenant_id"]
        tid_q = quote_plus(tid)

        # Add comments
        for comment in case_def.get("comments", []):
            with contextlib.suppress(httpx.HTTPError):
                await client.post(
                    f"{case_url}/v1/cases/{case_id}/comments?tenant_id={tid_q}",
                    json={"author": comment["author"], "body": comment["body"]},
                )

        # Add labels
        labels = case_def.get("labels", [])
        if labels:
            with contextlib.suppress(httpx.HTTPError):
                await client.post(
                    f"{case_url}/v1/cases/{case_id}/labels?tenant_id={tid_q}",
                    json={"labels": labels},
                )

        # Transition to target status
        target = case_def.get("target_status", "open")
        if target != "open":
            with contextlib.suppress(httpx.HTTPError):
                await client.patch(
                    f"{case_url}/v1/cases/{case_id}?tenant_id={tid_q}",
                    json={"status": target},
                )

        print(f"    Case '{case_def['title'][:50]}...' → {target}")


async def seed_disputes(client: httpx.AsyncClient, case_url: str, trace_ids: list[str]) -> None:
    """Create synthetic dispute records for dispute workflows."""
    dispute_templates = [
        {
            "entity_id": "fraud_frank",
            "dispute_type": "chargeback",
            "reason_code": "fraudulent",
            "amount": 1499.99,
            "currency": "USD",
            "merchant_id": "CryptoExchange",
            "card_network": "visa",
        },
        {
            "entity_id": "user_bob",
            "dispute_type": "retrieval",
            "reason_code": "unauthorized",
            "amount": 289.50,
            "currency": "USD",
            "merchant_id": "ElectronicsStore",
            "card_network": "mastercard",
        },
        {
            "entity_id": "mule_ivan",
            "dispute_type": "chargeback",
            "reason_code": "card_not_present",
            "amount": 899.00,
            "currency": "USD",
            "merchant_id": "WireTransfer",
            "card_network": "amex",
        },
        {
            "entity_id": "user_carol",
            "dispute_type": "chargeback",
            "reason_code": "service_not_received",
            "amount": 119.99,
            "currency": "USD",
            "merchant_id": "StreamingBundle",
            "card_network": "visa",
        },
    ]
    print(f"  Creating {len(dispute_templates)} disputes ...")
    created = 0
    for idx, template in enumerate(dispute_templates):
        trace = trace_ids[idx] if idx < len(trace_ids) else str(uuid.uuid4())
        body = {"tenant_id": TENANT_ID, "trace_id": trace, **template}
        try:
            r = await client.post(f"{case_url}/v1/disputes", json=body)
            if r.status_code in (200, 201):
                created += 1
        except httpx.HTTPError:
            pass
    print(f"    Disputes created: {created}")


async def seed_entity_lists(client: httpx.AsyncClient, decision_url: str) -> None:
    """Populate allow/block lists used in Entity Lists UI."""
    entries = {
        "blocklist": [
            {"entity_id": "fraud_frank", "reason": "Known fraud ring leader"},
            {"entity_id": "fraud_gina", "reason": "Shared emulator and mule links"},
            {"entity_id": "dev_emulator_003", "reason": "Automated emulator fingerprint"},
        ],
        "allowlist": [
            {"entity_id": "user_alice", "reason": "Trusted long-tenured customer"},
            {"entity_id": "acc_alice_main", "reason": "Verified payroll account"},
        ],
        "watchlist": [
            {"entity_id": "mule_ivan", "reason": "Potential mule behavior"},
            {"entity_id": "fraud_henry", "reason": "Associated with prior fraud case"},
        ],
    }
    total = sum(len(v) for v in entries.values())
    print(f"  Creating {total} entity-list entries ...")
    created = 0
    for list_type, list_entries in entries.items():
        for item in list_entries:
            body = {
                "tenant_id": TENANT_ID,
                "entity_id": item["entity_id"],
                "reason": item["reason"],
                "created_by": "demo_seed",
                "metadata": {"source": "demo_seed"},
            }
            try:
                r = await client.post(f"{decision_url}/v1/lists/{list_type}", json=body)
                if r.status_code in (200, 201):
                    created += 1
            except httpx.HTTPError:
                pass
    print(f"    Entity-list entries created: {created}")


async def seed_integrations(client: httpx.AsyncClient, ingress_url: str) -> None:
    """Install and configure a few integrations for Integration Hub screens."""
    demo_integrations = [
        ("ip_quality_score", {"api_key": "demo-ipqualityscore-key"}),
        ("fingerprintjs", {"api_key": "demo-fingerprintjs-key"}),
        ("sift", {"api_key": "demo-sift-key"}),
        ("sendgrid", {"api_key": "demo-sendgrid-key"}),
        ("opensanctions", {"api_key": "demo-opensanctions-key"}),
        ("jira", {"username": "demo-user", "password": "demo-pass"}),
    ]
    print(f"  Installing {len(demo_integrations)} integrations ...")
    installed = 0
    configured = 0
    for provider_id, config in demo_integrations:
        try:
            r1 = await client.post(
                f"{ingress_url}/v1/integrations/install",
                json={"tenant_id": TENANT_ID, "provider_id": provider_id, "config": config},
            )
            if r1.status_code in (200, 201):
                installed += 1
        except httpx.HTTPError:
            pass
        try:
            r2 = await client.post(
                f"{ingress_url}/v1/integrations/configure",
                json={"tenant_id": TENANT_ID, "provider_id": provider_id, "config": config},
            )
            if r2.status_code in (200, 201):
                configured += 1
        except httpx.HTTPError:
            pass
    print(f"    Integrations installed: {installed}, configured: {configured}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(
    decision_url: str,
    case_url: str,
    graph_url: str,
    ingress_url: str,
    force: bool,
) -> None:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        print("Checking service health ...")
        decision_ok = False
        try:
            r = await client.get(f"{decision_url}/v1/health")
            r.raise_for_status()
            decision_ok = True
            print("  ✓ decision-api is up")
        except httpx.HTTPError as exc:
            print(f"  ✗ decision-api at {decision_url} is not reachable: {exc}")

        case_ok = False
        try:
            r = await client.get(f"{case_url}/v1/health")
            r.raise_for_status()
            case_ok = True
            print("  ✓ case-api is up")
        except httpx.HTTPError as exc:
            print(f"  – case-api at {case_url} is not reachable: {exc}")

        graph_ok = False
        try:
            r = await client.get(f"{graph_url}/v1/health")
            if r.status_code == 200:
                graph_ok = True
                print("  ✓ graph-service is up")
        except httpx.HTTPError as exc:
            print(f"  ✗ graph-service at {graph_url} is not reachable: {exc}")

        require_seed_planes(decision_ok=decision_ok, graph_ok=graph_ok)

        ingress_available = False
        try:
            r = await client.get(f"{ingress_url}/v1/health")
            if r.status_code == 200:
                ingress_available = True
                print("  ✓ integration-ingress is up")
        except httpx.HTTPError:
            print("  – integration-ingress not available (skipping integration seed)")

        if case_ok and not force:
            if await _already_seeded(client, case_url):
                print(
                    "\nDemo data already exists for tenant 'demo'. Use --force to re-seed (additive)."
                )
                return

        print()
        print("Seeding decisions ...")
        trace_ids = await seed_decisions(client, decision_url)
        print(f"  Collected {len(trace_ids)} trace IDs\n")

        if case_ok:
            print("Seeding investigation cases ...")
            await seed_cases(client, case_url, trace_ids)
            print()
            print("Seeding disputes ...")
            await seed_disputes(client, case_url, trace_ids)
            print()
        else:
            print("Skipping cases and disputes (case-api unavailable)\n")

        print("Seeding entity lists ...")
        await seed_entity_lists(client, decision_url)
        print()

        if ingress_available:
            print("Seeding integrations ...")
            await seed_integrations(client, ingress_url)
            print()
        else:
            print("Skipping integrations seed (service unavailable)\n")

        print("Done! Demo data seeded for tenant 'demo'.")
        print(f"  Decision API: {decision_url}/docs")
        print(f"  Case API:     {case_url}/docs")
        print(f"  Graph API:    {graph_url}/docs")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data into Tarka")
    parser.add_argument(
        "--decision-url",
        default="http://localhost:8000",
        help="Decision API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--case-url",
        default="http://localhost:8002",
        help="Case API base URL (default: http://localhost:8002)",
    )
    parser.add_argument(
        "--graph-url",
        default="http://localhost:8001",
        help="Graph Service base URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--ingress-url",
        default="http://localhost:8003",
        help="Integration Ingress base URL (default: http://localhost:8003)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even if demo data already exists (additive)",
    )
    args = parser.parse_args()
    asyncio.run(
        main(args.decision_url, args.case_url, args.graph_url, args.ingress_url, args.force)
    )


if __name__ == "__main__":
    cli()
