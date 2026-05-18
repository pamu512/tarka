"""Messaging-driven SAR SFTP worker (FOR UPDATE SKIP LOCKED + immutable audit)."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from case_api.config import settings
from case_api.db import SessionLocal
from case_api.models import SARFiling, SarFiling
from case_api.sar_filing_transport import build_sar_transmission_package, upload_sar_bytes
from case_api.sar_transport import (
    SAR_ACKNOWLEDGED,
    SAR_FAILED,
    SAR_TRANSMITTED,
    claim_next_sftp_queued_intent,
    transition_sar_intent,
)

log = logging.getLogger("case_api.sar_transport_worker")

SAR_TRANSPORT_RUN_SUBJECT = "tarka.case.sar.transport.run"


async def process_sar_transport_once() -> bool:
    """Process at most one ``SFTP_QUEUED`` SAR intent. Returns ``True`` if a row was claimed (even if later FAILED)."""
    async with SessionLocal() as session:
        async with session.begin():
            intent = await claim_next_sftp_queued_intent(session)
            if intent is None:
                return False
            host = (settings.fincen_bsa_sftp_host or "").strip()
            if not host:
                await transition_sar_intent(
                    session,
                    intent,
                    to_status=SAR_FAILED,
                    actor="sar_worker",
                    detail={"reason_code": "SAR_SFTP_HOST_MISSING"},
                    stack_trace=None,
                )
                return True
            res = await session.execute(
                select(SARFiling).where(SARFiling.id == intent.sar_artifact_id)
            )
            art = res.scalar_one_or_none()
            if art is None:
                await transition_sar_intent(
                    session,
                    intent,
                    to_status=SAR_FAILED,
                    actor="sar_worker",
                    detail={
                        "reason_code": "SAR_ARTIFACT_MISSING",
                        "sar_artifact_id": str(intent.sar_artifact_id),
                    },
                    stack_trace=None,
                )
                return True
            if not (settings.fincen_bsa_sftp_user or "").strip():
                await transition_sar_intent(
                    session,
                    intent,
                    to_status=SAR_FAILED,
                    actor="sar_worker",
                    detail={"reason_code": "SAR_SFTP_USER_MISSING"},
                    stack_trace=None,
                )
                return True
            fname, body = build_sar_transmission_package(intent, art)
            try:
                await asyncio.to_thread(
                    upload_sar_bytes,
                    host=host,
                    port=int(settings.fincen_bsa_sftp_port),
                    username=settings.fincen_bsa_sftp_user.strip(),
                    password=settings.fincen_bsa_sftp_password or "",
                    remote_dir=settings.fincen_bsa_sftp_remote_dir,
                    filename=fname,
                    body=body,
                )
            except Exception:
                tb = traceback.format_exc()
                await transition_sar_intent(
                    session,
                    intent,
                    to_status=SAR_FAILED,
                    actor="sar_worker",
                    detail={"reason_code": "SAR_TRANSPORT_FAILED", "remote_filename": fname},
                    stack_trace=tb,
                )
                return True
            await transition_sar_intent(
                session,
                intent,
                to_status=SAR_TRANSMITTED,
                actor="sar_worker",
                detail={
                    "reason_code": "SAR_TRANSMITTED",
                    "remote_filename": fname,
                    "bytes": len(body),
                },
            )
            if not settings.sar_transport_require_separate_ack:
                await transition_sar_intent(
                    session,
                    intent,
                    to_status=SAR_ACKNOWLEDGED,
                    actor="sar_worker",
                    detail={
                        "reason_code": "SAR_ACK_AUTO",
                        "note": "ACK promoted in-band; set SAR_TRANSPORT_REQUIRE_SEPARATE_ACK=1 for decoupled FinCEN ACK ingestion.",
                    },
                )
            return True


async def handle_sar_transport_message(_subject: str, _payload: bytes) -> None:
    try:
        processed = await process_sar_transport_once()
        if processed:
            log.debug("sar transport tick processed one intent")
    except Exception:
        log.exception("sar transport handler failed")


async def _tick_loop(broker: Any, stop: asyncio.Event) -> None:
    try:
        await asyncio.sleep(min(5.0, settings.sar_transport_tick_seconds))
        while not stop.is_set():
            try:
                await broker.publish(SAR_TRANSPORT_RUN_SUBJECT, b"{}")
            except Exception as e:
                log.warning("sar transport publish tick failed: %s", e)
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=float(settings.sar_transport_tick_seconds)
                )
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        return


async def setup_sar_transport_worker(application: FastAPI) -> None:
    """Install :class:`tarka_core.messaging.MessageBroker` subscriber + periodic SAR dequeue ticks."""
    from tarka_core.messaging import LocalAsyncBroker, MessageBroker, NatsBroker

    broker: MessageBroker
    if (settings.nats_url or "").strip():
        try:
            import nats

            nc = await nats.connect(settings.nats_url)
            broker = NatsBroker(nc, nc.jetstream())
            log.info("SAR worker using NATS at %s", settings.nats_url)
        except Exception as e:
            log.warning("NATS unavailable for SAR worker (%s); using LocalAsyncBroker", e)
            broker = LocalAsyncBroker()
            await broker.start()
    else:
        broker = LocalAsyncBroker()
        await broker.start()
        log.info("SAR worker using LocalAsyncBroker (set NATS_URL for multi-pod dequeue fanout)")

    application.state.message_broker = broker
    application.state._sar_transport_sub = await broker.subscribe(
        SAR_TRANSPORT_RUN_SUBJECT, handle_sar_transport_message
    )

    stop = asyncio.Event()
    application.state._sar_transport_stop = stop
    application.state._sar_transport_tick_task = asyncio.create_task(_tick_loop(broker, stop))


async def shutdown_sar_transport_worker(application: FastAPI) -> None:
    stop = getattr(application.state, "_sar_transport_stop", None)
    if stop is not None:
        stop.set()
    tick = getattr(application.state, "_sar_transport_tick_task", None)
    if tick is not None:
        tick.cancel()
        try:
            await tick
        except asyncio.CancelledError:
            pass
    broker = getattr(application.state, "message_broker", None)
    if broker is None:
        return
    try:
        await broker.aclose()
    except Exception:
        log.exception("message broker close failed")
