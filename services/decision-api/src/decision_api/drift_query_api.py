from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from decision_api.calibration_api import compute_drift_for_tenant

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/drift", tags=["drift"])

SCHEMA_ID = "tarka.drift_query/v1"


@router.get("/query")
async def drift_query(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    profile: str = Query(default="default", max_length=64),
    _user=Depends(require_role("analyst")),
):
    """Unified tenant drift summary (calibration histogram drift)."""
    calibration = compute_drift_for_tenant(tenant_id, profile)
    hint = str(calibration.get("hint") or "")
    elevated = hint in {
        "elevated_bin_shift_review_calibration",
        "moderate_drift_monitor",
    }
    return {
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant_id,
        "profile": profile,
        "calibration": calibration,
        "summary": {
            "drift_elevated": elevated,
            "drift_score": calibration.get("drift_score"),
            "hint": hint,
        },
    }


@router.get("/calibration")
async def drift_calibration(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    profile: str = Query(default="default", max_length=64),
    _user=Depends(require_role("analyst")),
):
    """Tenant-scoped calibration drift (alias for calibration histogram comparison)."""
    return compute_drift_for_tenant(tenant_id, profile)
