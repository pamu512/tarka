"""Aggregate honesty gates for customer diligence (not SOC2 attestation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from decision_api.feature_store_posture import load_feature_store_ops_posture
from decision_api.l3_ops_ledger import public_view as l3_public_view
from decision_api.loyalty_feed_posture import load_loyalty_feed_ops_posture
from decision_api.partner_fusion_status import load_partner_fusion_status

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Only files that exist in-repo; missing → incomplete (fail closed for pack ready).
_INDEX_PATHS = [
    "docs/compliance/CLAIM_LOCK.md",
    "docs/compliance/partner-fusion-proof.stable.sha256",
    "docs/compliance/partner-fusion-proof.live.status",
    "docs/docs/guides/feature-serving-contract.md",
    "docs/docs/guides/partner-enrichment-fusion.md",
    "scripts/audit_stubs.py",
    "scripts/compliance/export_control_evidence_index.py",
    "scripts/oss/loyalty_feed_posture_smoke.py",
]


def _index_presence() -> dict[str, Any]:
    items = []
    missing: list[str] = []
    for rel in _INDEX_PATHS:
        ok = (_REPO_ROOT / rel).is_file()
        items.append({"path": rel, "exists": ok})
        if not ok:
            missing.append(rel)
    return {
        "schema_id": "tarka.diligence_doc_index/v1",
        "items": items,
        "missing": missing,
        "complete": not missing,
    }


def load_diligence_readiness(
    *,
    rules_path: str,
    redis_url: str = "",
    loyalty_abuse_url: str = "",
    loyalty_abuse_api_key: str = "",
) -> dict[str, Any]:
    """Machine-readable diligence blockers — never forges LIVE / L3 / Feast / Motiva."""
    l2 = load_partner_fusion_status()
    l3 = l3_public_view()
    feeds = load_loyalty_feed_ops_posture(
        loyalty_abuse_url=loyalty_abuse_url,
        loyalty_abuse_api_key=loyalty_abuse_api_key,
    )
    store = load_feature_store_ops_posture(rules_path=rules_path, redis_url=redis_url)
    docs = _index_presence()

    gates = {
        "l2_partner_fusion": {
            "status": l2.get("status"),
            "live_claim_allowed": bool(l2.get("promote_live_claim_allowed")),
            "ready_to_attempt_live_proof": bool(
                (l2.get("live_readiness") or {}).get("ready_to_attempt_live_proof")
            ),
        },
        "l3_ops_ledger": {
            "status": l3.get("status"),
            "claim_allowed": bool(l3.get("claim_allowed")),
            "tenant_id": l3.get("tenant_id"),
        },
        "loyalty_feeds_c1": {
            "status": (feeds.get("feeds_status") or {}).get("status"),
            "live_claim_allowed": bool(feeds.get("live_claim_allowed")),
            "bridge_configured": bool(feeds.get("bridge_configured")),
        },
        "feature_store": {
            "ops_ready": bool(store.get("ops_ready")),
            "feast_class_claim_allowed": bool(store.get("feast_class_claim_allowed")),
            "streaming_flink_claim_allowed": bool(
                store.get("streaming_flink_claim_allowed")
            ),
            "dual_diff_proven": bool(
                (store.get("offline_parity") or {}).get("dual_diff_proven")
            ),
        },
        "control_docs": {
            "complete": bool(docs.get("complete")),
            "missing_count": len(docs.get("missing") or []),
        },
        "sanctions_screening": {
            "plane": "integration_ingress",
            "posture": "GET /v1/ops/sanctions-screening-posture",
            "screen_persist": "POST /v1/ops/sanctions-screen",
            "cronjob_example": "infra/deploy/examples/sanctions-refresh-cronjob.yaml",
            "motiva_claim_allowed": False,
            "note": (
                "continuous_ops_ready requires FtM cache + TARKA_SANCTIONS_REFRESH_SCHEDULE "
                "+ refresh stamp; motiva_claim_allowed stays false"
            ),
        },
    }

    blockers: list[str] = []
    if not gates["l2_partner_fusion"]["live_claim_allowed"]:
        blockers.append(f"l2_{gates['l2_partner_fusion']['status'] or 'unknown'}")
    if not gates["l3_ops_ledger"]["claim_allowed"]:
        blockers.append(f"l3_{gates['l3_ops_ledger']['status'] or 'NOT_STARTED'}")
    if not gates["loyalty_feeds_c1"]["live_claim_allowed"]:
        blockers.append("loyalty_feeds_not_proven")
    if not gates["feature_store"]["ops_ready"]:
        blockers.append("feature_store_ops_not_ready")
    if not docs["complete"]:
        blockers.append("control_docs_incomplete")

    return {
        "schema_id": "tarka.diligence_readiness/v1",
        "soc2_attestation": False,
        "diligence_pack_ready": bool(docs["complete"]),
        "closed_loop_claims_ready": False,  # requires L2 LIVE + L3 COMPLETE + feeds
        "gates": gates,
        "blockers": blockers,
        "doc_index": docs,
        "honesty": (
            "Customer diligence index — not SOC2 Type II. closed_loop_claims_ready stays "
            "false until LIVE partner pin, L3 COMPLETE, and FEEDS_READY. See CLAIM_LOCK."
        ),
        "pack": "docs/compliance/CLAIM_LOCK.md",
        "export": "scripts/compliance/export_control_evidence_index.py",
        "ui": "/compliance",
    }
