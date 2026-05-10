from __future__ import annotations

import os
import sys
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import get_session
from case_api.models import InvestigationTemplate
from case_api.schemas import (
    CreateInvestigationTemplateRequest,
    InvestigationTemplateOut,
    PatchInvestigationTemplateRequest,
)

"""Tenant-scoped investigation templates (Marble #56): CRUD + apply via ``playbook_id`` on cases."""

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/investigation-templates", tags=["investigation-templates"])


@router.get("", response_model=dict)
async def list_templates(
    tenant_id: str = Query(..., description="Tenant scope"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    q = (
        select(InvestigationTemplate)
        .where(InvestigationTemplate.tenant_id == tenant_id)
        .order_by(InvestigationTemplate.slug)
    )
    rows = (await session.execute(q)).scalars().all()
    return {
        "items": [InvestigationTemplateOut.model_validate(r).model_dump(mode="json") for r in rows]
    }


@router.post("", response_model=InvestigationTemplateOut, status_code=201)
async def create_template(
    body: CreateInvestigationTemplateRequest,
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    exists = await session.scalar(
        select(InvestigationTemplate.id).where(
            InvestigationTemplate.tenant_id == body.tenant_id,
            InvestigationTemplate.slug == body.slug,
        ),
    )
    if exists:
        raise HTTPException(409, "template slug already exists for tenant")
    apply_cfg = body.apply.model_dump(mode="json", exclude_none=True)
    row = InvestigationTemplate(
        tenant_id=body.tenant_id,
        slug=body.slug,
        name=body.name,
        apply_config=apply_cfg,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return InvestigationTemplateOut.model_validate(row)


@router.get("/{template_id}", response_model=InvestigationTemplateOut)
async def get_template(
    template_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    row = await session.scalar(
        select(InvestigationTemplate).where(
            InvestigationTemplate.id == template_id,
            InvestigationTemplate.tenant_id == tenant_id,
        ),
    )
    if not row:
        raise HTTPException(404, "not found")
    return InvestigationTemplateOut.model_validate(row)


@router.patch("/{template_id}", response_model=InvestigationTemplateOut)
async def patch_template(
    template_id: uuid.UUID,
    body: PatchInvestigationTemplateRequest,
    tenant_id: str = Query(..., description="Tenant scope"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    row = await session.scalar(
        select(InvestigationTemplate).where(
            InvestigationTemplate.id == template_id,
            InvestigationTemplate.tenant_id == tenant_id,
        ),
    )
    if not row:
        raise HTTPException(404, "not found")
    if body.name is not None:
        row.name = body.name
    if body.apply is not None:
        patch_apply = body.apply.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        merged = dict(row.apply_config or {})
        merged.update(patch_apply)
        row.apply_config = merged
    await session.commit()
    await session.refresh(row)
    return InvestigationTemplateOut.model_validate(row)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    res = await session.execute(
        delete(InvestigationTemplate).where(
            InvestigationTemplate.id == template_id,
            InvestigationTemplate.tenant_id == tenant_id,
        ),
    )
    await session.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "not found")
    return Response(status_code=204)
