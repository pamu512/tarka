"""HTTP surface for marketplace seller KYB workflow (INFORM-shaped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402

from decision_api.kyb_rescreen import (  # noqa: E402
    apply_rescreen_result,
    rescreen_ops_posture,
    select_due_sellers,
)
from decision_api.marketplace_kyb import (  # noqa: E402
    KYB_STATES,
    apply_suspicious_activity_report,
    apply_transition,
    empty_seller_record,
    evaluate_kyb_gate,
    normalize_state,
)
from decision_api.marketplace_kyb_store import kyb_store  # noqa: E402

router = APIRouter(prefix="/v1/marketplace/kyb", tags=["marketplace-kyb"])


class KybUpsertBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    seller_id: str = Field(..., min_length=1, max_length=256)
    seller_gmv_30d: float = Field(default=0.0, ge=0)
    disclosure_complete: bool = False
    collect_started_at: str | None = Field(default=None, max_length=64)
    high_volume_threshold: float = Field(default=5000.0, ge=0)
    sla_hours: int = Field(default=72, ge=1, le=720)


class KybTransitionBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    seller_id: str = Field(..., min_length=1, max_length=256)
    to_state: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(default="", max_length=512)
    vendor_status: str | None = Field(default=None, max_length=128)
    disclosure_complete: bool | None = None
    seller_gmv_30d: float | None = Field(default=None, ge=0)
    collect_started_at: str | None = Field(default=None, max_length=64)


class KybGateBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    seller_id: str = Field(..., min_length=1, max_length=256)
    kyb_state: str | None = None
    seller_gmv_30d: float = Field(default=0.0, ge=0)
    high_volume_threshold: float = Field(default=5000.0, ge=0)
    collect_started_at: str | None = None
    sla_hours: int = Field(default=72, ge=1, le=720)
    vendor_verified: bool = False
    disclosure_complete: bool = False


class SuspiciousActivityBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    seller_id: str = Field(..., min_length=1, max_length=256)
    report_id: str = Field(..., min_length=1, max_length=128)
    reporter_id: str = Field(default="", max_length=128)
    category: str = Field(default="other", max_length=64)
    narrative: str = Field(default="", max_length=2000)
    force_suspend: bool = False
    seller_gmv_30d: float | None = Field(default=None, ge=0)


class RescreenResultBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    seller_id: str = Field(..., min_length=1, max_length=256)
    hit: bool
    vendor_status: str = Field(default="", max_length=128)
    reason: str = Field(default="continuous_rescreen", max_length=256)


def _gate_from_row(
    row: dict[str, Any],
    *,
    high_volume_threshold: float = 5000.0,
    sla_hours: int = 72,
    vendor_verified: bool | None = None,
) -> dict[str, Any]:
    verified = vendor_verified
    if verified is None:
        verified = str(row.get("vendor_status") or "").lower() in (
            "approved",
            "verified",
            "green",
            "completed",
        )
    return evaluate_kyb_gate(
        kyb_state=str(row.get("kyb_state")),
        seller_gmv_30d=float(row.get("seller_gmv_30d") or 0),
        high_volume_threshold=high_volume_threshold,
        collect_started_at=row.get("collect_started_at"),
        sla_hours=sla_hours,
        vendor_verified=bool(verified),
        disclosure_complete=bool(row.get("disclosure_complete")),
    )


@router.get("/states")
async def list_kyb_states(_user=Depends(require_role("analyst"))) -> dict[str, Any]:
    return {
        "states": list(KYB_STATES),
        "schema_id": "tarka.marketplace_kyb_states/v1",
        "store_backend": kyb_store.backend(),
    }


@router.get("/sellers/{tenant_id}/{seller_id}")
async def get_seller_kyb(
    tenant_id: str,
    seller_id: str,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    row = await kyb_store.get(tenant_id, seller_id)
    if row is None:
        raise HTTPException(status_code=404, detail="seller_kyb_not_found")
    return {
        "seller": row,
        "gate": _gate_from_row(row),
        "store_backend": kyb_store.backend(),
    }


@router.put("/sellers")
async def upsert_seller_kyb(
    body: KybUpsertBody,
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    row = await kyb_store.get(body.tenant_id, body.seller_id) or empty_seller_record(
        tenant_id=body.tenant_id, seller_id=body.seller_id
    )
    row["seller_gmv_30d"] = float(body.seller_gmv_30d)
    row["disclosure_complete"] = bool(body.disclosure_complete)
    if body.collect_started_at is not None:
        row["collect_started_at"] = body.collect_started_at
    row = await kyb_store.put(body.tenant_id, body.seller_id, row)
    return {
        "seller": row,
        "gate": _gate_from_row(
            row,
            high_volume_threshold=body.high_volume_threshold,
            sla_hours=body.sla_hours,
        ),
        "store_backend": kyb_store.backend(),
    }


@router.post("/sellers/transition")
async def transition_seller_kyb(
    body: KybTransitionBody,
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    if normalize_state(body.to_state) not in KYB_STATES:
        raise HTTPException(status_code=400, detail="invalid_kyb_state")
    row = await kyb_store.get(body.tenant_id, body.seller_id) or empty_seller_record(
        tenant_id=body.tenant_id, seller_id=body.seller_id
    )
    if body.seller_gmv_30d is not None:
        row["seller_gmv_30d"] = float(body.seller_gmv_30d)
    if body.disclosure_complete is not None:
        row["disclosure_complete"] = bool(body.disclosure_complete)
    if body.collect_started_at is not None:
        row["collect_started_at"] = body.collect_started_at
    if normalize_state(body.to_state) == "collecting" and not row.get(
        "collect_started_at"
    ):
        from datetime import UTC, datetime

        row["collect_started_at"] = datetime.now(UTC).isoformat()
    try:
        row = apply_transition(
            row,
            body.to_state,
            reason=body.reason,
            vendor_status=body.vendor_status,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    row = await kyb_store.put(body.tenant_id, body.seller_id, row)
    return {
        "seller": row,
        "gate": _gate_from_row(row),
        "store_backend": kyb_store.backend(),
    }


@router.post("/suspicious-activity")
async def report_suspicious_activity(
    body: SuspiciousActivityBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """INFORM-shaped consumer report intake → KYB collect / suspend_sales."""
    row = await kyb_store.get(body.tenant_id, body.seller_id) or empty_seller_record(
        tenant_id=body.tenant_id, seller_id=body.seller_id
    )
    if body.seller_gmv_30d is not None:
        row["seller_gmv_30d"] = float(body.seller_gmv_30d)
    row = apply_suspicious_activity_report(
        row,
        report_id=body.report_id,
        reporter_id=body.reporter_id,
        category=body.category,
        narrative=body.narrative,
        force_suspend=body.force_suspend,
    )
    row = await kyb_store.put(body.tenant_id, body.seller_id, row)
    return {
        "seller": row,
        "gate": _gate_from_row(row),
        "report_count": len(row.get("suspicious_reports") or []),
        "store_backend": kyb_store.backend(),
    }


@router.post("/gate")
async def kyb_gate_evaluate(
    body: KybGateBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Stateless gate for evaluate bridges (reads store when present)."""
    stored = await kyb_store.get(body.tenant_id, body.seller_id)
    state = body.kyb_state
    gmv = body.seller_gmv_30d
    disclose = body.disclosure_complete
    collect_at = body.collect_started_at
    if stored:
        state = state or str(stored.get("kyb_state"))
        if body.seller_gmv_30d == 0.0 and stored.get("seller_gmv_30d"):
            gmv = float(stored["seller_gmv_30d"])
        if collect_at is None:
            collect_at = stored.get("collect_started_at")
        if not body.disclosure_complete and stored.get("disclosure_complete"):
            disclose = bool(stored["disclosure_complete"])
    gate = evaluate_kyb_gate(
        kyb_state=state,
        seller_gmv_30d=gmv,
        high_volume_threshold=body.high_volume_threshold,
        collect_started_at=collect_at,
        sla_hours=body.sla_hours,
        vendor_verified=body.vendor_verified,
        disclosure_complete=disclose,
    )
    return {
        "gate": gate,
        "seller_id": body.seller_id,
        "tenant_id": body.tenant_id,
        "store_backend": kyb_store.backend(),
    }


@router.get("/rescreen/due")
async def kyb_rescreen_due(
    max_age_days: int = 30,
    limit: int = 100,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Sellers due for continuous re-screen (file/memory snapshot)."""
    due = select_due_sellers(
        kyb_store.list_memory_records(),
        max_age_days=max_age_days,
        limit=limit,
    )
    return {
        "due": due,
        "count": len(due),
        "posture": rescreen_ops_posture(due_count=len(due), max_age_days=max_age_days),
        "store_backend": kyb_store.backend(),
        "motiva_claim_allowed": False,
    }


@router.post("/rescreen/result")
async def kyb_rescreen_result(
    body: RescreenResultBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Apply OpenSanctions/identity_kyb rescreen hit/clear to KYB state."""
    stored = await kyb_store.get(body.tenant_id, body.seller_id)
    if not stored:
        stored = empty_seller_record(tenant_id=body.tenant_id, seller_id=body.seller_id)
        stored["kyb_state"] = "verified"
    row = apply_rescreen_result(
        stored,
        hit=body.hit,
        vendor_status=body.vendor_status,
        reason=body.reason,
    )
    row = await kyb_store.put(body.tenant_id, body.seller_id, row)
    return {
        "seller": row,
        "gate": _gate_from_row(row),
        "store_backend": kyb_store.backend(),
        "motiva_claim_allowed": False,
    }
