"""Embedded executive KPIs with Redis cache (5m TTL) and strict RBAC."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.redis_store import redis_tags  # noqa: E402

router = APIRouter(prefix="/v1/analytics/dashboards", tags=["analytics-dashboards"])

_CACHE_PREFIX = "tarka:dashboard:kpis:"
_TTL = int(os.environ.get("DASHBOARD_KPI_CACHE_TTL_SECONDS", "300"))


def _stub_kpis(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "approval_rate_pct": None,
        "fraud_rate_pct": None,
        "sla_breach_count_7d": None,
        "note": "Wire ClickHouse read-only role + bounded queries; stub until CH credentials configured.",
    }


@router.get("/kpis")
async def get_dashboard_kpis(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Analyst+ (admin included); tenant binding enforced when API key maps tenants."""
    auth = getattr(request.state, "auth_user", None)
    if auth and auth.tenant_ids and "*" not in auth.tenant_ids and tenant_id not in auth.tenant_ids:
        raise HTTPException(403, "tenant not permitted for this credential")
    key = f"{_CACHE_PREFIX}{tenant_id}"
    if redis_tags._client:
        try:
            raw = await redis_tags._client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    body = _stub_kpis(tenant_id)
    if redis_tags._client:
        try:
            await redis_tags._client.set(key, json.dumps(body), ex=_TTL)
        except Exception:
            pass
    return body
