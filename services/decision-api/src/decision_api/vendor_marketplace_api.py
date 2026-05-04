"""Vendor marketplace HTTP surface (list + test invoke with dynamic timeout)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.vendors.cost_router import maybe_invoke_vendor
from decision_api.vendors.registry import list_registered_vendors

router = APIRouter(prefix="/v1/vendors", tags=["vendors"])


class VendorProbeRequest(BaseModel):
    vendor_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=128)
    entity_id: str = Field(..., max_length=256)
    features: dict[str, object] = Field(default_factory=dict)
    base_rule_score: float = Field(default=60.0)
    budget_ms: float = Field(default=800.0, ge=50.0, le=5000.0)


@router.get("/registry")
async def vendor_registry(_user=Depends(require_role("analyst"))) -> dict[str, object]:
    return {"vendors": list_registered_vendors()}


@router.post("/probe")
async def vendor_probe(
    request: Request,
    body: VendorProbeRequest,
    _user=Depends(require_role("admin")),
) -> dict[str, object]:
    """Invoke a registered vendor with a dynamic latency budget (ops smoke test)."""
    http: httpx.AsyncClient = request.app.state.http
    sig = await maybe_invoke_vendor(
        http,
        vendor_id=body.vendor_id,
        tenant_id=body.tenant_id,
        entity_id=body.entity_id,
        features=body.features,
        base_rule_score=body.base_rule_score,
        budget_ms=body.budget_ms,
    )
    if sig is None:
        return {"skipped": True, "reason": "unknown_vendor_or_cost_gate"}
    return {
        "vendor_id": sig.vendor_id,
        "score_0_100": sig.score_0_100,
        "reason_codes": sig.reason_codes,
        "raw_meta": sig.raw_meta,
    }
