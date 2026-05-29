"""Tarka Command Center — unified ops cockpit aggregate (Prompt 188)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PKG_DIR = Path(__file__).resolve().parent
_SIBLING_CACHE: dict[str, Any] = {}


def _load_sibling(module_name: str) -> Any:
    """Load a co-located module without importing ``integration_ingress`` package init."""
    cached = _SIBLING_CACHE.get(module_name)
    if cached is not None:
        return cached
    path = _PKG_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"integration_ingress_{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _SIBLING_CACHE[module_name] = mod
    return mod


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_command_center_payload(*, tenant_id: str) -> dict[str, Any]:
    """Aggregate high-signal KPIs and module deep-links for the analyst landing cockpit."""
    tid = (tenant_id or "demo").strip() or "demo"

    promo = _load_sibling("promo_abuse_tracking").build_promo_abuse_payload(
        tenant_id=tid, coupon_code="NEWUSER50"
    )
    syn = _load_sibling("synthetic_identity_detectors").build_synthetic_identity_payload(
        tenant_id=tid, limit=50
    )
    social = _load_sibling("social_engineering_monitor").build_social_engineering_payload(
        tenant_id=tid, limit=40
    )
    rings = _load_sibling("review_ring_clusters").build_review_ring_payload(tenant_id=tid, limit=12)
    seller = _load_sibling("seller_integrity").build_seller_integrity_payload(
        tenant_id=tid, limit=40
    )
    payout = _load_sibling("payout_delay_automation").build_payout_delay_payload(
        tenant_id=tid, limit=35
    )
    kyc = _load_sibling("kyc_handover").build_kyc_handover_board(tenant_id=tid)
    regional = _load_sibling("regional_risk_toggles").build_regional_risk_payload(tenant_id=tid)

    hero_kpis = [
        {
            "id": "open_cases",
            "label": "Cases needing review",
            "value": 3,
            "delta": "+1 vs yesterday",
            "tone": "amber",
            "route": "/cases",
        },
        {
            "id": "held_payouts",
            "label": "Payouts on hold",
            "value": payout["summary"]["held_count"],
            "delta": f"${payout['summary']['held_amount_usd']:,.0f} USD",
            "tone": "violet",
            "route": "/integrations/payout-delay",
        },
        {
            "id": "syn_id",
            "label": "Synthetic ID flags",
            "value": syn["summary"]["flagged_users"],
            "delta": f"{syn['summary']['scanned_users']} scanned",
            "tone": "fuchsia",
            "route": "/investigation/synthetic-identity",
        },
        {
            "id": "regions_blocked",
            "label": "Regions blacklisted",
            "value": regional["summary"]["blacklisted_count"],
            "delta": f"{regional['summary']['critical_wave_count']} critical waves",
            "tone": "rose",
            "route": "/compliance/regional-risk",
        },
    ]

    action_queue: list[dict[str, Any]] = []

    for row in kyc["cases"]:
        if row.get("handover_status") == "pending" and row.get("kyc_status") == "needs_more_id":
            action_queue.append(
                {
                    "id": f"kyc-{row['case_id']}",
                    "title": f"Send KYC ID email — {row['case_id']}",
                    "description": f"{row['display_name']} · {row['subject_email']}",
                    "route": f"/cases/{row['case_id']}",
                    "priority": "high",
                    "module": "compliance",
                },
            )

    if promo["summary"]["unique_users"] >= promo["thresholds"]["warn_unique_users"]:
        action_queue.append(
            {
                "id": "promo-newuser50",
                "title": "Promo abuse spike — NEWUSER50",
                "description": f"{promo['summary']['unique_users']} unique redeemers",
                "route": "/analytics/promo-abuse",
                "priority": "elevated",
                "module": "analytics",
            },
        )

    if social["summary"]["flagged_accounts"] > 0:
        action_queue.append(
            {
                "id": "social-eng",
                "title": "Social engineering credential bursts",
                "description": f"{social['summary']['flagged_accounts']} flagged accounts",
                "route": "/investigation/social-engineering",
                "priority": "high",
                "module": "investigation",
            },
        )

    for cluster in rings["clusters"][:2]:
        if int(cluster.get("suspicion_score", 0)) >= 70:
            action_queue.append(
                {
                    "id": f"ring-{cluster['cluster_id']}",
                    "title": f"Review ring — {cluster['member_count']} users",
                    "description": "Identical 5-product review overlap",
                    "route": "/analytics/review-rings",
                    "priority": "elevated",
                    "module": "analytics",
                },
            )

    action_queue = action_queue[:8]

    modules: list[dict[str, Any]] = [
        _mod("cases", "Cases queue", "/cases", "cases", "Open triage", "3", "amber"),
        _mod(
            "investigation",
            "Investigation Copilot",
            "/investigation",
            "investigation",
            "Saarthi",
            "Ready",
            "normal",
        ),
        _mod("graph", "Graph Explorer", "/graph", "graph", "Entity risk", "Live", "normal"),
        _mod(
            "mule_path",
            "Mule path",
            "/graph/mule-path",
            "graph",
            "Fund flows",
            "Demo paths",
            "normal",
        ),
        _mod(
            "synthetic_identity",
            "Synthetic identity",
            "/investigation/synthetic-identity",
            "investigation",
            "Flagged users",
            str(syn["summary"]["flagged_users"]),
            "fuchsia" if syn["summary"]["flagged_users"] else "normal",
        ),
        _mod(
            "social_engineering",
            "Social engineering",
            "/investigation/social-engineering",
            "investigation",
            "Credential bursts",
            str(social["summary"]["flagged_accounts"]),
            "orange" if social["summary"]["flagged_accounts"] else "normal",
        ),
        _mod(
            "promo_abuse",
            "Promo abuse",
            "/analytics/promo-abuse",
            "analytics",
            "NEWUSER50 users",
            str(promo["summary"]["unique_users"]),
            promo["summary"]["abuse_risk"],
        ),
        _mod(
            "review_rings",
            "Review rings",
            "/analytics/review-rings",
            "analytics",
            "Clusters",
            str(rings["summary"]["cluster_count"]),
            "cyan",
        ),
        _mod(
            "seller_integrity",
            "Seller integrity",
            "/integrations/seller-integrity",
            "integrations",
            "At-risk sellers",
            str(seller["summary"]["at_risk_sellers"]),
            "amber" if seller["summary"]["at_risk_sellers"] else "normal",
        ),
        _mod(
            "payout_delay",
            "Payout delay",
            "/integrations/payout-delay",
            "integrations",
            "Held payouts",
            str(payout["summary"]["held_count"]),
            "violet" if payout["summary"]["held_count"] else "normal",
        ),
        _mod(
            "kyc_handover",
            "KYC handover",
            "/compliance/kyc-handover",
            "compliance",
            "Pending emails",
            str(kyc["summary"]["pending_email_count"]),
            "teal" if kyc["summary"]["pending_email_count"] else "normal",
        ),
        _mod(
            "regional_risk",
            "Regional risk",
            "/compliance/regional-risk",
            "compliance",
            "Blacklisted",
            str(regional["summary"]["blacklisted_count"]),
            "rose" if regional["summary"]["blacklisted_count"] else "normal",
        ),
        _mod(
            "webhook_logs",
            "Webhook logs",
            "/integrations/webhook-logs",
            "integrations",
            "Block signals",
            "Live",
            "normal",
        ),
        _mod(
            "rate_limits",
            "Rate limit shields",
            "/integrations/rate-limit-shields",
            "integrations",
            "API keys",
            "Shields",
            "normal",
        ),
        _mod(
            "system_health",
            "System health HUD",
            "/ops/system-health",
            "compliance",
            "Planes",
            "Monitor",
            "normal",
        ),
        _mod(
            "failover",
            "Failover toggles",
            "/ops/failover-toggles",
            "compliance",
            "Graph / AI",
            "Toggles",
            "normal",
        ),
        _mod(
            "audit_log",
            "Audit log",
            "/analytics/audit-log",
            "analytics",
            "Decisions",
            "Search",
            "normal",
        ),
        _mod("rules", "Rules", "/rules", "rules", "Policy", "Edit", "normal"),
    ]

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "hero_kpis": hero_kpis,
        "action_queue": action_queue,
        "modules": modules,
        "quick_links": [
            {"label": "Live transactions", "route": "/transactions/live", "module": "analytics"},
            {"label": "Command palette", "route": "#palette", "module": "dashboard", "hint": "⌘K"},
            {
                "label": "Encrypted fields",
                "route": "/compliance/encrypted-fields",
                "module": "compliance",
            },
            {
                "label": "System benchmarking",
                "route": "/ops/system-benchmarking",
                "module": "compliance",
            },
        ],
    }


def _mod(
    mid: str,
    title: str,
    route: str,
    module: str,
    metric_label: str,
    metric_value: str,
    tone: str,
) -> dict[str, Any]:
    return {
        "id": mid,
        "title": title,
        "route": route,
        "module": module,
        "metric_label": metric_label,
        "metric_value": metric_value,
        "tone": tone,
    }
