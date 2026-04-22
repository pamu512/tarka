from __future__ import annotations

"""Policy DAG helpers (OSS #31): stable cohort buckets and champion–challenger comparison.

Canary routing for JSON rule packs uses the same stable bucket as ``json_rules._pack_experiment_bucket``;
this module documents the salt semantics and exposes helpers for audit metadata.
"""


import hashlib
from typing import Any

from decision_api.config import settings


def _cohort_digest_hex(tenant_id: str, entity_id: str, salt: str) -> str:
    raw = f"{tenant_id}|{entity_id}|{salt}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def cohort_bucket_0_99(tenant_id: str, entity_id: str, salt: str = "policy_v1") -> int:
    """Deterministic 0..99 bucket for an entity (same construction as canary_percent gating)."""
    return int(_cohort_digest_hex(tenant_id, entity_id, salt)[:8], 16) % 100


def build_canary_cohort_audit(
    tenant_id: str,
    entity_id: str,
    *,
    salt_version: str,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """OSS #47 — stable cohort fields for audit / dashboards (hash-stable stickiness).

    * ``cohort_sticky_id`` — first 16 hex chars of SHA256(tenant|entity|salt); stable join key.
    * ``cohort_bucket_0_99`` — same bucket as JSON rule canary routing when salt matches pack key semantics.
    """
    digest = _cohort_digest_hex(tenant_id, entity_id, salt_version)
    out: dict[str, Any] = {
        "schema_version": 1,
        "cohort_sticky_id": digest[:16],
        "cohort_bucket_0_99": int(digest[:8], 16) % 100,
        "salt_version": salt_version,
    }
    if experiment_id and str(experiment_id).strip():
        out["experiment_id"] = str(experiment_id).strip()[:128]
    return out


def decision_from_rule_score(rule_score: float) -> str:
    """Map a blended rule-era score to allow/review/deny (mirrors main evaluate thresholds)."""
    if rule_score >= settings.deny_threshold:
        return "deny"
    if rule_score >= settings.review_threshold:
        return "review"
    return "allow"


def build_policy_routing_audit(
    *,
    cohort_bucket: int,
    cohort_salt: str,
    champion_rule_score: float,
    challenger_rule_score: float,
    champion_decision: str,
    challenger_decision: str,
    ml_score: float | None,
) -> dict[str, Any]:
    """Structured block for audit payload_snapshot.policy_routing (champion–challenger analysis)."""
    return {
        "cohort_bucket_0_99": cohort_bucket,
        "cohort_salt": cohort_salt,
        "champion_rule_score": round(champion_rule_score, 4),
        "challenger_rule_score": round(challenger_rule_score, 4),
        "champion_decision": champion_decision,
        "challenger_decision": challenger_decision,
        "decisions_agree": champion_decision == challenger_decision,
        "ml_score": ml_score,
    }
