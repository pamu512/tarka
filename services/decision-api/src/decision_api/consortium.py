import hashlib
import hmac
from typing import Any


def hash_entity_id(consortium_secret: str, tenant_id: str, entity_id: str) -> str:
    secret = (consortium_secret or "tarka-default-consortium-secret").encode("utf-8")
    payload = f"{tenant_id.strip()}::{entity_id.strip()}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def consortium_score_delta(data: dict[str, Any], min_tenants: int = 2) -> float:
    tenant_count = int(data.get("tenant_count", 0) or 0)
    report_count = int(data.get("report_count", 0) or 0)
    max_severity = float(data.get("max_severity", 0.0) or 0.0)
    if tenant_count < max(1, min_tenants):
        return 0.0
    # Weighted to avoid overreaction with sparse reports.
    return min(30.0, (tenant_count * 5.0) + (report_count * 1.5) + (max_severity * 8.0))
