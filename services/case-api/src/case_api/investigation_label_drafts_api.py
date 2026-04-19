"""Durable analyst-scoped investigation label drafts (separate from case workflow labels)."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import get_session
from case_api.models import InvestigationLabelDraft
from case_api.schemas import LabelDraftBatchIn, LabelDraftOut, LabelDraftRowIn

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/investigation-label-drafts", tags=["investigation-label-drafts"])

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_SAFE_ENTITY = re.compile(r"^[a-zA-Z0-9._@:/-]{1,512}$")
_VALID_Y = frozenset({"fraud", "legitimate", "unknown"})
_MAX_PER_ANALYST = 500


def _validate_row(row: LabelDraftRowIn) -> tuple[str | None, str | None, str, str, str | None]:
    y = str(row.y_label or "").strip().lower()
    if y not in _VALID_Y:
        raise HTTPException(400, f"invalid y_label: {row.y_label!r}")
    tid = (row.trace_id or "").strip() or None
    eid = (row.entity_id or "").strip() or None
    if tid and not _UUID.match(tid):
        raise HTTPException(400, f"invalid trace_id: {tid!r}")
    if eid and not _SAFE_ENTITY.match(eid):
        raise HTTPException(400, "invalid entity_id format")
    if not tid and not eid:
        raise HTTPException(400, "each row needs trace_id and/or entity_id")
    src = str(row.source or "analyst")[:128]
    notes = row.notes or None
    if notes is not None:
        notes = str(notes)[:4000]
    return tid, eid, y, src, notes


@router.post("/batch", response_model=dict)
async def batch_append(
    tenant_id: str,
    body: LabelDraftBatchIn,
    session: AsyncSession = Depends(get_session),
    _admin=Depends(require_role("admin")),
):
    analyst_id = str(body.analyst_id).strip()[:256]
    if not analyst_id:
        raise HTTPException(400, "analyst_id required")

    if body.clear_existing:
        await session.execute(
            delete(InvestigationLabelDraft).where(
                InvestigationLabelDraft.tenant_id == tenant_id,
                InvestigationLabelDraft.analyst_id == analyst_id,
            )
        )
        await session.flush()

    count_q = await session.execute(
        select(func.count())
        .select_from(InvestigationLabelDraft)
        .where(
            InvestigationLabelDraft.tenant_id == tenant_id,
            InvestigationLabelDraft.analyst_id == analyst_id,
        )
    )
    cur = int(count_q.scalar() or 0)
    n = min(len(body.rows), 50)
    overflow = (cur + n - _MAX_PER_ANALYST) if n > 0 else 0
    if overflow > 0:
        subq = await session.execute(
            select(InvestigationLabelDraft.id)
            .where(
                InvestigationLabelDraft.tenant_id == tenant_id,
                InvestigationLabelDraft.analyst_id == analyst_id,
            )
            .order_by(InvestigationLabelDraft.created_at.asc())
            .limit(overflow)
        )
        ids = list(subq.scalars().all())
        if ids:
            await session.execute(delete(InvestigationLabelDraft).where(InvestigationLabelDraft.id.in_(ids)))
            await session.flush()

    added = 0
    for raw in body.rows[:50]:
        tid, eid, y, src, notes = _validate_row(raw)
        session.add(
            InvestigationLabelDraft(
                tenant_id=tenant_id,
                analyst_id=analyst_id,
                trace_id=tid,
                entity_id=eid,
                y_label=y,
                source=src,
                notes=notes,
            )
        )
        added += 1

    await session.commit()

    count_q2 = await session.execute(
        select(func.count())
        .select_from(InvestigationLabelDraft)
        .where(
            InvestigationLabelDraft.tenant_id == tenant_id,
            InvestigationLabelDraft.analyst_id == analyst_id,
        )
    )
    total = int(count_q2.scalar() or 0)
    return {"ok": True, "added": added, "stored_total": total, "max_per_analyst": _MAX_PER_ANALYST}


@router.get("", response_model=dict)
async def list_drafts(
    tenant_id: str,
    analyst_id: str,
    session: AsyncSession = Depends(get_session),
    limit: int = 200,
    _analyst=Depends(require_role("analyst")),
):
    analyst_id = str(analyst_id).strip()[:256]
    lim = max(1, min(limit, 500))
    result = await session.execute(
        select(InvestigationLabelDraft)
        .where(
            InvestigationLabelDraft.tenant_id == tenant_id,
            InvestigationLabelDraft.analyst_id == analyst_id,
        )
        .order_by(InvestigationLabelDraft.updated_at.desc())
        .limit(lim)
    )
    rows = result.scalars().all()
    return {
        "items": [LabelDraftOut.model_validate(r).model_dump() for r in rows],
        "total": len(rows),
    }


@router.delete("", response_model=dict)
async def clear_drafts(
    tenant_id: str,
    analyst_id: str,
    session: AsyncSession = Depends(get_session),
    _admin=Depends(require_role("admin")),
):
    analyst_id = str(analyst_id).strip()[:256]
    r = await session.execute(
        delete(InvestigationLabelDraft).where(
            InvestigationLabelDraft.tenant_id == tenant_id,
            InvestigationLabelDraft.analyst_id == analyst_id,
        )
    )
    await session.commit()
    return {"ok": True, "deleted": r.rowcount}


@router.delete("/{draft_id}", response_model=dict)
async def delete_one(
    draft_id: uuid.UUID,
    tenant_id: str,
    analyst_id: str,
    session: AsyncSession = Depends(get_session),
    _admin=Depends(require_role("admin")),
):
    analyst_id = str(analyst_id).strip()[:256]
    result = await session.execute(
        select(InvestigationLabelDraft).where(
            InvestigationLabelDraft.id == draft_id,
            InvestigationLabelDraft.tenant_id == tenant_id,
            InvestigationLabelDraft.analyst_id == analyst_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "draft not found")
    await session.delete(row)
    await session.commit()
    return {"ok": True}
