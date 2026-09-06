"""Event type allow-list HTTP: seed ∪ overlay ∪ env."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth_rbac import require_role
from decision_api.config import settings
from decision_api.db import get_session
from decision_api.event_type_gate import event_type_allow_list
from decision_api.event_type_store import list_names, upsert_name
from tarka_shared.ingest_contract_v1 import validate_event_type_shape

router = APIRouter(prefix="/v1/event-types", tags=["event-types"])
_require_analyst = require_role("analyst")

_DEMO_PUT_DETAIL = "event types persist on product Postgres"


class EventTypeIn(BaseModel):
    tenant_id: str
    name: str


def _refuse_demo_put() -> None:
    if settings.tarka_desk_profile.strip().lower() == "demo":
        raise HTTPException(403, _DEMO_PUT_DETAIL)


def _require_tenant_id(tenant_id: str | None) -> str:
    if tenant_id is None or not str(tenant_id).strip():
        raise HTTPException(400, "tenant_id is required")
    return str(tenant_id).strip()


@router.get("")
async def get_event_types(
    tenant_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, list[str]]:
    tid = _require_tenant_id(tenant_id)
    try:
        overlay = frozenset(await list_names(session, tid))
    except Exception as exc:
        raise HTTPException(503, "event type store unavailable") from exc
    names = sorted(event_type_allow_list(overlay))
    return {"names": names}


@router.put("")
async def put_event_type(
    body: EventTypeIn,
    session: AsyncSession = Depends(get_session),
    _user=Depends(_require_analyst),
) -> dict[str, str]:
    _refuse_demo_put()
    tid = _require_tenant_id(body.tenant_id)
    try:
        name = validate_event_type_shape(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        await upsert_name(session, tid, name)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "event type store unavailable") from exc
    return {"tenant_id": tid, "name": name}
