"""``POST/GET /v1/entities/{entity_id}/hil-overrides`` — HIL context override ingress."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analytics.hil_context_store import HilContextOverrideStore, HilContextStoreError
from config import get_settings
from database import TarkaDatabaseException
from middleware.idempotency import release_lock, verify_and_lock_event
from models.operational_signals import OperationalSignalDAO
from schemas.hil_overrides import (
    HilOverrideAcceptedResponse,
    HilOverrideCreate,
    HilOverrideListResponse,
)
from services.hil_override_ingress import apply_hil_override_with_audit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Entity resolution"])


def _idempotency_redis_key(idempotency_key: str) -> str:
    prefix = get_settings().hil_override_idempotency_redis_prefix
    return f"{prefix}{idempotency_key}"


def _require_redis_client(request: Request) -> object:
    redis_client = getattr(request.app.state, "anumana_redis", None)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="hil override ingress requires Redis idempotency backing",
        )
    return redis_client


def _require_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory = getattr(request.app.state, "audit_session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="hil override persistence is unavailable (audit database not configured)",
        )
    return session_factory


def _require_hil_store(request: Request) -> HilContextOverrideStore:
    store = getattr(request.app.state, "hil_context_override_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="hil override store unavailable (ClickHouse not configured)",
        )
    return store


async def _fetch_existing_event_id(
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_key: str,
) -> UUID | None:
    async with session_factory() as session:
        row = await OperationalSignalDAO.fetch_by_idempotency_key(session, idempotency_key)
        if row is None:
            return None
        return row.id


@router.post(
    "/entities/{entity_id}/hil-overrides",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=HilOverrideAcceptedResponse,
    summary="Apply analyst HIL context override",
    description=(
        "Writes a row to ``tarka_analytics.hil_context_overrides`` (ClickHouse) and persists an "
        "audit anchor in ``operational_signals`` with idempotent Redis locking."
    ),
)
async def create_hil_override(
    request: Request,
    entity_id: UUID,
    body: HilOverrideCreate,
) -> HilOverrideAcceptedResponse:
    redis_client = _require_redis_client(request)
    session_factory = _require_session_factory(request)
    store = _require_hil_store(request)

    redis_key = _idempotency_redis_key(body.idempotency_key)
    lock_acquired = await verify_and_lock_event(
        redis_client,
        redis_key,
        ttl_seconds=get_settings().hil_override_idempotency_ttl_sec,
    )

    if not lock_acquired:
        existing_id = await _fetch_existing_event_id(session_factory, body.idempotency_key)
        if existing_id is not None:
            async with session_factory() as session:
                row = await OperationalSignalDAO.fetch_by_idempotency_key(
                    session,
                    body.idempotency_key,
                )
            meta = (row.metadata_json if row is not None else None) or {}
            return HilOverrideAcceptedResponse(
                event_id=existing_id,
                override={
                    "tenant_id": body.tenant_id,
                    "entity_id": str(entity_id),
                    "override_type": meta.get("override_type"),
                    "scope_key": meta.get("scope_key"),
                    "expires_at": meta.get("expires_at"),
                    "analyst_rationale": meta.get("analyst_rationale"),
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="hil override with this idempotency_key is already in progress",
        )

    try:
        event_id, override_row = await apply_hil_override_with_audit(
            store=store,
            session_factory=session_factory,
            entity_id=entity_id,
            body=body,
        )
    except IntegrityError:
        existing_id = await _fetch_existing_event_id(session_factory, body.idempotency_key)
        if existing_id is None:
            logger.exception(
                "hil_override_integrity_error idempotency_key=%s",
                body.idempotency_key,
            )
            await release_lock(redis_client, redis_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="hil override idempotency conflict",
            ) from None
        event_id = existing_id
        override_row = {
            "tenant_id": body.tenant_id,
            "entity_id": str(entity_id),
            "override_type": body.override_type.value,
            "scope_key": body.scope_key,
            "expires_at": (body.expires_at.isoformat() if body.expires_at else None),
            "analyst_rationale": body.analyst_rationale,
        }
    except HilContextStoreError as exc:
        await release_lock(redis_client, redis_key)
        logger.exception("hil_override_clickhouse_failed entity_id=%s", entity_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"hil override ClickHouse write failed: {exc}",
        ) from exc
    except TarkaDatabaseException as exc:
        await release_lock(redis_client, redis_key)
        logger.exception(
            "hil_override_persist_failed idempotency_key=%s error=%s",
            body.idempotency_key,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="hil override operational signal persistence failed",
        ) from exc

    logger.info(
        "hil_override_accepted event_id=%s entity_id=%s override_type=%s",
        event_id,
        entity_id,
        body.override_type.value,
    )
    return HilOverrideAcceptedResponse(event_id=event_id, override=override_row)


@router.get(
    "/entities/{entity_id}/hil-overrides",
    response_model=HilOverrideListResponse,
    summary="List active HIL context overrides",
    description="Returns non-expired rows from ``tarka_analytics.hil_context_overrides`` for the entity.",
)
async def list_hil_overrides(
    request: Request,
    entity_id: UUID,
    tenant_id: str,
) -> HilOverrideListResponse:
    store = _require_hil_store(request)
    tenant = (tenant_id or "").strip()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_id query parameter is required",
        )
    try:
        rows = store.list_active_overrides(tenant_id=tenant, entity_id=str(entity_id))
    except HilContextStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"hil override fetch failed: {exc}",
        ) from exc
    return HilOverrideListResponse(
        tenant_id=tenant,
        entity_id=str(entity_id),
        overrides=rows,
    )
