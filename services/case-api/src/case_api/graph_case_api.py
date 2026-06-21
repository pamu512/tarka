from __future__ import annotations

import os
import sys
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import CaseGraphAnnotation
from .schemas import GraphAnnotationsIn, GraphAnnotationsOut

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(tags=["case-graph"])

_lock = Lock()
_usage_events: dict[str, int] = defaultdict(int)


def _storage_key(tenant_id: str, case_id: uuid.UUID) -> str:
    return f"tarka.graphAnnotations.v1:{tenant_id}:{case_id}"


def _record_usage(surface: str, tenant_id: str) -> None:
    with _lock:
        _usage_events[f"{surface}|{tenant_id}"] += 1


def usage_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "schema_id": "tarka.explainability_usage/v1",
            "service": "case-api",
            "events_by_key": dict(_usage_events),
            "total_events": sum(_usage_events.values()),
        }


async def _case_for_tenant(session: AsyncSession, case_id: uuid.UUID, tenant_id: str):
    from main import _case_for_tenant as _load

    return await _load(session, case_id, tenant_id)


def _validate_annotations(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in raw.items():
        node_id = str(key).strip()
        if not node_id or len(node_id) > 512:
            continue
        note = str(val).strip()
        if not note:
            continue
        out[node_id] = note[:2000]
    if len(out) > 500:
        raise HTTPException(400, "too many annotation entries (max 500)")
    return out


@router.get("/v1/cases/{case_id}/graph-annotations", response_model=GraphAnnotationsOut)
async def get_graph_annotations(
    case_id: uuid.UUID,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    row = (
        await session.execute(
            select(CaseGraphAnnotation).where(
                CaseGraphAnnotation.tenant_id == tenant_id,
                CaseGraphAnnotation.case_id == case.id,
            )
        )
    ).scalar_one_or_none()
    annotations: dict[str, str] = {}
    updated_by = None
    updated_at = None
    if row is not None:
        raw = row.annotations if isinstance(row.annotations, dict) else {}
        annotations = {str(k): str(v) for k, v in raw.items()}
        updated_by = row.updated_by
        updated_at = row.updated_at
    _record_usage("graph_annotations_read", tenant_id)
    return GraphAnnotationsOut(
        case_id=case.id,
        tenant_id=tenant_id,
        annotations=annotations,
        storage_key=_storage_key(tenant_id, case.id),
        updated_by=updated_by,
        updated_at=updated_at,
    )


@router.put("/v1/cases/{case_id}/graph-annotations", response_model=GraphAnnotationsOut)
async def put_graph_annotations(
    case_id: uuid.UUID,
    body: GraphAnnotationsIn,
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    session: AsyncSession = Depends(get_session),
    _analyst=Depends(require_role("analyst")),
):
    case = await _case_for_tenant(session, case_id, tenant_id)
    annotations = _validate_annotations(body.annotations)
    analyst = (body.analyst_id or "").strip()[:256] or None
    row = (
        await session.execute(
            select(CaseGraphAnnotation).where(
                CaseGraphAnnotation.tenant_id == tenant_id,
                CaseGraphAnnotation.case_id == case.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = CaseGraphAnnotation(
            tenant_id=tenant_id,
            case_id=case.id,
            annotations=annotations,
            updated_by=analyst,
        )
        session.add(row)
    else:
        row.annotations = annotations
        row.updated_by = analyst
    await session.commit()
    await session.refresh(row)
    _record_usage("graph_annotations_write", tenant_id)
    return GraphAnnotationsOut(
        case_id=case.id,
        tenant_id=tenant_id,
        annotations=annotations,
        storage_key=_storage_key(tenant_id, case.id),
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


@router.get("/v1/cases/{case_id}/path-explain")
async def case_path_explain(
    case_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Query(..., description="Tenant scope; must match the case"),
    to_entity_id: str | None = None,
    depth: int = 3,
    decay: float = 0.5,
    limit: int = 10,
    _analyst=Depends(require_role("analyst")),
):
    from config import settings

    case = await _case_for_tenant(session, case_id, tenant_id)
    base = (settings.graph_service_url or "").strip().rstrip("/")
    if not base:
        raise HTTPException(503, "GRAPH_SERVICE_URL not set")
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "from_entity_id": case.entity_id,
        "depth": depth,
        "decay": decay,
        "limit": limit,
    }
    if to_entity_id:
        params["to_entity_id"] = to_entity_id
    http: httpx.AsyncClient = request.app.state.http
    try:
        r = await http.get(
            f"{base}/v1/analytics/path-explain",
            params=params,
            timeout=12.0,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text[:400]) from exc
    except Exception as exc:
        raise HTTPException(503, "graph_service_unreachable") from exc
    payload = r.json()
    payload["case_id"] = str(case_id)
    _record_usage("path_explain", tenant_id)
    return payload


@router.get("/v1/explainability/usage")
async def explainability_usage(_admin=Depends(require_role("admin"))):
    return usage_snapshot()
