"""``POST /v1/operational-signals`` — durable ingress for operational feedback signals."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from database import TarkaDatabaseException, atomic_transaction
from middleware.idempotency import release_lock, verify_and_lock_event
from models.operational_signals import OperationalSignalDAO
from schemas.operational_signals import (
    OperationalSignalAcceptedResponse,
    OperationalSignalCreate,
)
from services.operational_signal_persist import (
    persist_operational_signal_with_shadow_retro_tag,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Operational signals"])


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{get_settings().operational_signal_idempotency_redis_prefix}{idempotency_key}"


def _require_redis_client(request: Request) -> object:
    redis_client = getattr(request.app.state, "anumana_redis", None)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operational signal ingress requires Redis idempotency backing",
        )
    return redis_client


def _require_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory = getattr(request.app.state, "audit_session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operational signal persistence is unavailable (audit database not configured)",
        )
    return session_factory


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
    "/operational-signals",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OperationalSignalAcceptedResponse,
    summary="Ingest an operational feedback signal",
    description=(
        "Accepts chargebacks, refunds, reversals, and analyst manual overrides. "
        "Requires ``X-Auth-Token`` (see router-level auth dependency). "
        "Persists ``operational_signals`` and enqueues ``SHADOW_RETRO_TAG`` on ``tarka_outbox`` "
        "inside one ACID transaction."
    ),
)
async def create_operational_signal(
    request: Request,
    body: OperationalSignalCreate,
) -> OperationalSignalAcceptedResponse:
    redis_client = _require_redis_client(request)
    session_factory = _require_session_factory(request)

    redis_key = _idempotency_redis_key(body.idempotency_key)
    lock_acquired = await verify_and_lock_event(
        redis_client,
        redis_key,
        ttl_seconds=get_settings().operational_signal_idempotency_ttl_sec,
    )

    if not lock_acquired:
        existing_id = await _fetch_existing_event_id(session_factory, body.idempotency_key)
        if existing_id is not None:
            return OperationalSignalAcceptedResponse(event_id=existing_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="operational signal with this idempotency_key is already in progress",
        )

    try:
        async with atomic_transaction(session_factory) as session:
            row = await persist_operational_signal_with_shadow_retro_tag(session, body)
            event_id = row.id
    except IntegrityError:
        existing_id = await _fetch_existing_event_id(session_factory, body.idempotency_key)
        if existing_id is None:
            logger.exception(
                "operational_signal_integrity_error idempotency_key=%s",
                body.idempotency_key,
            )
            await release_lock(redis_client, redis_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="operational signal idempotency conflict",
            ) from None
        event_id = existing_id
    except TarkaDatabaseException as exc:
        await release_lock(redis_client, redis_key)
        logger.exception(
            "operational_signal_persist_failed idempotency_key=%s error=%s",
            body.idempotency_key,
            exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operational signal persistence failed",
        ) from exc

    logger.info(
        "operational_signal_accepted event_id=%s signal_type=%s entity_id=%s shadow_retro_outbox=enqueued",
        event_id,
        body.signal_type.value,
        body.entity_id,
    )
    return OperationalSignalAcceptedResponse(event_id=event_id)
