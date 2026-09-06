"""Field registry HTTP surface: seed ∪ overlay, maps, discover."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_rbac import require_role
from decision_api.config import settings
from decision_api.db import get_session
from decision_api.field_store import (
    FieldRegistrySeedLocked,
    FieldRegistryUnknownName,
    get_overlay,
    list_maps,
    list_overlay,
    upsert_map,
    upsert_overlay,
)
from field_registry import (
    discover_payload,
    load_seed_rows,
    merge_registry_rows,
    validate_registry_name,
)

router = APIRouter(prefix="/v1/fields", tags=["fields"])
_require_analyst = require_role("analyst")

_DEMO_PUT_DETAIL = "maps persist on product Postgres"


class OverlayIn(BaseModel):
    explanation: str
    source: str


class MapIn(BaseModel):
    tenant_id: str
    buyer_key: str
    registry_name: str


class DiscoverIn(BaseModel):
    tenant_id: str
    payload: dict[str, Any]


def _refuse_demo_put() -> None:
    if settings.tarka_desk_profile.strip().lower() == "demo":
        raise HTTPException(403, _DEMO_PUT_DETAIL)


def _require_tenant_id(tenant_id: str | None) -> str:
    if tenant_id is None or not str(tenant_id).strip():
        raise HTTPException(400, "tenant_id is required")
    return str(tenant_id).strip()


def _overlay_dict(row: Any) -> dict[str, str]:
    return {"name": row.name, "explanation": row.explanation, "source": row.source}


def _map_dict(row: Any) -> dict[str, str]:
    return {
        "tenant_id": row.tenant_id,
        "buyer_key": row.buyer_key,
        "registry_name": row.registry_name,
    }


@router.get("")
async def list_fields(
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> list[dict[str, str]]:
    tid = _require_tenant_id(tenant_id)
    try:
        overlay_rows = await list_overlay(session, tid)
    except Exception as exc:
        raise HTTPException(503, "field registry store unavailable") from exc
    overlay = [_overlay_dict(r) for r in overlay_rows]
    return merge_registry_rows(seed=load_seed_rows(), overlay=overlay)


@router.get("/maps")
async def get_maps(
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> list[dict[str, str]]:
    tid = _require_tenant_id(tenant_id)
    try:
        rows = await list_maps(session, tid)
    except Exception as exc:
        raise HTTPException(503, "field registry store unavailable") from exc
    return [_map_dict(r) for r in rows]


@router.put("/maps")
async def put_map(
    body: MapIn,
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, str]:
    _refuse_demo_put()
    tid = _require_tenant_id(body.tenant_id)
    try:
        row = await upsert_map(session, tid, body.buyer_key, body.registry_name)
        await session.commit()
    except FieldRegistryUnknownName as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _map_dict(row)


@router.post("/discover")
async def discover(
    body: DiscoverIn,
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, Any]:
    tid = _require_tenant_id(body.tenant_id)
    try:
        overlay_rows = await list_overlay(session, tid)
        map_rows = await list_maps(session, tid)
    except Exception as exc:
        raise HTTPException(503, "field registry store unavailable") from exc
    overlay = [_overlay_dict(r) for r in overlay_rows]
    merged = merge_registry_rows(seed=load_seed_rows(), overlay=overlay)
    names = {r["name"] for r in merged}
    maps = {m.buyer_key: m.registry_name for m in map_rows}
    return discover_payload(body.payload, registry_names=names, maps=maps)


@router.get("/{name}")
async def get_field(
    name: str,
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, str]:
    tid = _require_tenant_id(tenant_id)
    stripped = name.strip()
    try:
        overlay = await get_overlay(session, tid, stripped)
    except Exception as exc:
        raise HTTPException(503, "field registry store unavailable") from exc
    if overlay is not None:
        return _overlay_dict(overlay)
    for row in load_seed_rows():
        if row.get("name") == stripped:
            return row
    raise HTTPException(404, f"unknown field '{stripped}'")


@router.put("/{name}")
async def put_field(
    name: str,
    body: OverlayIn,
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, str]:
    _refuse_demo_put()
    try:
        validated = validate_registry_name(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    tid = _require_tenant_id(tenant_id)
    try:
        row = await upsert_overlay(
            session, tid, validated, body.explanation, body.source
        )
        await session.commit()
    except FieldRegistrySeedLocked as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _overlay_dict(row)
