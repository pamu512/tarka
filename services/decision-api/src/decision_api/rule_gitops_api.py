"""Maker/Checker metadata for visual rule packs; durable audit rows (SR-11)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.deps import get_pg_pool  # noqa: E402

log = logging.getLogger("decision-api")

router = APIRouter(prefix="/v1/rules/gitops", tags=["rule-gitops"])


class ApprovalRecord(BaseModel):
    pack_name: str = Field(..., max_length=120)
    fingerprint_sha256: str = Field(..., min_length=64, max_length=64)
    approved_by: str = Field(..., max_length=256)
    notes: str = Field(default="", max_length=2000)


@router.post("/approve")
async def record_maker_checker_approval(
    body: ApprovalRecord,
    pool: asyncpg.Pool = Depends(get_pg_pool),
    user=Depends(require_role("admin")),
) -> dict[str, Any]:
    """Persist approval metadata and return the stored audit_token."""
    audit_token = secrets.token_urlsafe(32)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rule_approvals (
                    pack_name, fingerprint_sha256, actor_user_id, audit_token, created_at
                )
                VALUES ($1, $2, $3, $4, now())
                RETURNING id, audit_token, created_at
                """,
                body.pack_name,
                body.fingerprint_sha256,
                user.user_id,
                audit_token,
            )
    except Exception as e:
        log.warning("rule_approvals insert failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "APPROVAL_PERSISTENCE_FAILED",
                "message": "Could not persist rule approval; try again later.",
            },
        ) from e

    if row is None:
        raise HTTPException(
            status_code=503,
            detail={"reason_code": "APPROVAL_PERSISTENCE_FAILED", "message": "Insert returned no row."},
        )
    created_at: datetime = row["created_at"]
    return {
        "status": "recorded",
        "approval_id": str(row["id"]),
        "audit_token": row["audit_token"],
        "approved_by": body.approved_by,
        "notes": body.notes,
        "recorded_at": created_at.isoformat(),
        "actor": user.user_id,
    }
