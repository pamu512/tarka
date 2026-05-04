"""Maker/Checker metadata for visual rule packs (integration with external GitOps is out-of-band)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/rules/gitops", tags=["rule-gitops"])


class ApprovalRecord(BaseModel):
    pack_name: str = Field(..., max_length=120)
    fingerprint_sha256: str = Field(..., min_length=64, max_length=64)
    approved_by: str = Field(..., max_length=256)
    notes: str = Field(default="", max_length=2000)


@router.post("/approve")
async def record_maker_checker_approval(
    body: ApprovalRecord,
    user=Depends(require_role("admin")),
) -> dict[str, object]:
    """Record an approval decision (store in your SOX system; this endpoint returns an audit token only)."""
    token = f"gitops-approve:{body.fingerprint_sha256[:16]}:{user.user_id}"
    return {
        "status": "recorded",
        "audit_token": token,
        "approved_by": body.approved_by,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "actor": user.user_id,
    }
