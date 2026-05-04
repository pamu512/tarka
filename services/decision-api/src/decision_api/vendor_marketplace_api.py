"""Vendor marketplace HTTP surface (list + test invoke with dynamic timeout)."""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.db import get_session  # noqa: E402
from decision_api.vendors.base import VendorTier  # noqa: E402
from decision_api.vendors.cost_router import PREMIUM_COST_SCORE_THRESHOLD, maybe_invoke_vendor  # noqa: E402
from decision_api.vendors.exceptions import (  # noqa: E402
    VendorAuditConfigurationError,
    VendorTimeoutError,
    VendorUpstreamError,
)
from decision_api.vendors.registry import get_adapter, list_registered_vendors  # noqa: E402

router = APIRouter(prefix="/v1/vendors", tags=["vendors"])


class VendorProbeRequest(BaseModel):
    vendor_id: str = Field(..., max_length=64)
    tenant_id: str = Field(..., max_length=128)
    entity_id: str = Field(..., max_length=256)
    features: dict[str, object] = Field(default_factory=dict)
    base_rule_score: float = Field(default=60.0)
    budget_ms: float = Field(default=800.0, ge=50.0, le=5000.0)
    trace_id: uuid.UUID | None = Field(
        default=None,
        description="Correlation id for Postgres audit; generated when omitted.",
    )


@router.get("/registry")
async def vendor_registry(_user=Depends(require_role("analyst"))) -> dict[str, object]:
    return {"vendors": list_registered_vendors()}


@router.post("/probe")
async def vendor_probe(
    request: Request,
    body: VendorProbeRequest,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("admin")),
) -> dict[str, object]:
    """Invoke a registered vendor with a dynamic latency budget (ops smoke test)."""
    adapter = get_adapter(body.vendor_id)
    if adapter is None:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "VENDOR_NOT_FOUND",
                "message": f"No vendor adapter registered for id={body.vendor_id!r}.",
                "registered_vendors": list_registered_vendors(),
            },
        )
    if adapter.tier == VendorTier.PREMIUM and body.base_rule_score < PREMIUM_COST_SCORE_THRESHOLD:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "VENDOR_UNAVAILABLE",
                "message": (
                    f"Vendor {body.vendor_id!r} is gated: premium adapters require base_rule_score "
                    f">= {PREMIUM_COST_SCORE_THRESHOLD} (got {body.base_rule_score})."
                ),
            },
        )
    http: httpx.AsyncClient = request.app.state.http
    trace_id = body.trace_id or uuid.uuid4()
    try:
        sig = await maybe_invoke_vendor(
            http,
            vendor_id=body.vendor_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            features=body.features,
            base_rule_score=body.base_rule_score,
            budget_ms=body.budget_ms,
            audit_session=session,
            trace_id=trace_id,
        )
    except VendorTimeoutError as e:
        raise HTTPException(status_code=504, detail=e.to_detail()) from e
    except VendorUpstreamError as e:
        raise HTTPException(status_code=502, detail=e.to_detail()) from e
    except VendorAuditConfigurationError as e:
        raise HTTPException(
            status_code=500,
            detail={"reason_code": getattr(e, "reason_code", "VENDOR_AUDIT_CONTEXT_MISSING"), "message": str(e)},
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "VENDOR_UNAVAILABLE",
                "message": f"Vendor invocation failed: {e!s}",
            },
        ) from e
    if sig is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "VENDOR_UNAVAILABLE",
                "message": "Vendor adapter returned no signal (unexpected).",
            },
        )
    return {
        "vendor_id": sig.vendor_id,
        "score_0_100": sig.score_0_100,
        "reason_codes": sig.reason_codes,
        "raw_meta": sig.raw_meta,
        "trace_id": str(trace_id),
    }
