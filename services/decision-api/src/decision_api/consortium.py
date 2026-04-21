import hashlib
import hmac
from typing import Any


def hash_entity_id(consortium_secret: str, tenant_id: str, entity_id: str, *, hash_scope: str = "consortium") -> str:
    secret = (consortium_secret or "tarka-default-consortium-secret").encode("utf-8")
    normalized_entity = entity_id.strip().lower()
    normalized_tenant = tenant_id.strip().lower()
    if hash_scope == "tenant":
        payload = f"tenant::{normalized_tenant}::entity::{normalized_entity}".encode("utf-8")
    else:
        # Cross-tenant sharing requires the same entity hash independent of tenant.
        payload = f"entity::{normalized_entity}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def consortium_score_delta(
    data: dict[str, Any],
    min_tenants: int = 2,
    *,
    min_reports: int = 3,
    trust_floor: float = 0.2,
    max_delta: float = 35.0,
) -> float:
    tenant_count = int(data.get("tenant_count", 0) or 0)
    report_count = int(data.get("report_count", 0) or 0)
    max_severity = float(data.get("max_severity", 0.0) or 0.0)
    weighted_tenant_score = float(data.get("weighted_tenant_score", tenant_count) or tenant_count)
    weighted_report_score = float(data.get("weighted_report_score", report_count) or report_count)
    false_positive_rate = float(data.get("false_positive_rate", 0.0) or 0.0)
    quality_score = float(data.get("quality_score", 1.0) or 1.0)
    trust_floor = max(0.05, min(0.8, float(trust_floor)))
    max_delta = max(1.0, min(100.0, float(max_delta)))
    min_reports = max(1, int(min_reports))
    if tenant_count < max(1, min_tenants):
        # cold-start prior: allow tiny signal if multiple reports exist even before min tenant count
        if report_count < min_reports:
            return 0.0
        return min(6.0, report_count * 1.2)
    raw = (weighted_tenant_score * 4.0) + (weighted_report_score * 1.2) + (max_severity * 8.0)
    # Penalize consortium signals with high false-positive feedback.
    adjusted = raw * max(trust_floor, 1.0 - min(1.0, false_positive_rate)) * max(trust_floor, min(1.5, quality_score))
    return min(max_delta, adjusted)
