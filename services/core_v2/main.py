from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Dict
from uuid import UUID

from redis.exceptions import RedisError
import structlog
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    cache_logger_on_first_use=True,
)

from db import (
    AuditLog,
    get_db_session,
    init_redis_pool,
    redis_client_for_publish,
    shutdown_redis_pool,
)
from ffi import run_rules

logger = structlog.get_logger(__name__)

SPEED_LAYER_CHANNEL = "tarka:decisions:stream"
"""Redis Stream for ML sidecars (exact key name for hybrid AI wiring)."""
DECISIONS_STREAM_LIGHTWEIGHT = "tarka:decisions_stream"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Boot/shutdown shared Redis pool from ``db``; failures are logged and the API stays up."""
    await init_redis_pool()
    yield
    await shutdown_redis_pool()


app = FastAPI(title="Tarka Core v2", version="0.1.0", lifespan=lifespan)


async def _publish_decision_to_speed_layer(payload_json: str) -> None:
    """
    Fire-and-forget pub/sub publish (legacy channel ``tarka:decisions:stream``).
    Must never raise into the HTTP stack.
    """
    client = redis_client_for_publish()
    if client is None:
        logger.warning(
            "speed_layer_publish_skipped",
            reason="redis_client_unavailable",
        )
        return
    try:
        connect_timeout = float(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", "2.0"))
        await asyncio.wait_for(
            client.publish(SPEED_LAYER_CHANNEL, payload_json),
            timeout=connect_timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "speed_layer_publish_timeout",
            channel=SPEED_LAYER_CHANNEL,
            exc_info=exc,
        )
    except RedisError as exc:
        logger.error(
            "speed_layer_publish_failed",
            channel=SPEED_LAYER_CHANNEL,
            exc_info=exc,
        )


async def _push_lightweight_decision_stream_event(
    entity_id: UUID,
    amount: float,
    decision: str,
) -> None:
    """
    Background task: ``XADD`` minimal fields for downstream consumers.

    Redis Stream field values are strings; failures must not affect HTTP responses.
    """
    client = redis_client_for_publish()
    if client is None:
        logger.warning(
            "redis_stream_publish_skipped",
            reason="redis_client_unavailable",
            stream=DECISIONS_STREAM_LIGHTWEIGHT,
        )
        return

    event = {
        "entity_id": str(entity_id),
        "amount": str(amount),
        "decision": decision,
    }
    try:
        await client.xadd(DECISIONS_STREAM_LIGHTWEIGHT, event)
    except Exception:
        pass


class TransactionPayload(BaseModel):
    """Inbound JSON body: unknown fields rejected (`extra='forbid'`)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    amount: float = Field(
        ...,
        gt=0,
        description="Strictly positive, finite floating-point amount.",
    )
    timestamp: datetime
    metadata: Dict[str, Any]

    @field_validator("amount")
    @classmethod
    def validate_amount_finite_and_positive(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be a finite float strictly greater than zero")
        if value <= 0:
            raise ValueError("amount must be strictly greater than zero")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata_is_string_keyed_mapping(
        cls, value: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("metadata must be a dictionary")
        for key in value:
            if not isinstance(key, str):
                raise ValueError("metadata keys must be strings")
        return value


class DecisionResponse(BaseModel):
    """Rust-backed rule outcome string (e.g. APPROVE / FLAG_REVIEW)."""

    model_config = ConfigDict(extra="forbid")

    decision: str


@app.post("/v1/decide", response_model=DecisionResponse)
async def decide(
    payload: TransactionPayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    background_tasks: BackgroundTasks,
) -> DecisionResponse:
    started = time.perf_counter()
    rust_decision: str | None = None
    database_commit_status = "not_attempted"

    try:
        payload_dict = payload.model_dump(mode="json")
        try:
            decision_str = run_rules(payload_dict)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rust_decision = decision_str

        audit_row = AuditLog(
            entity_id=payload.entity_id,
            raw_payload=payload_dict,
            decision=decision_str,
        )
        session.add(audit_row)
        try:
            await session.commit()
            database_commit_status = "committed"
        except SQLAlchemyError as exc:
            await session.rollback()
            database_commit_status = "failure"
            raise HTTPException(
                status_code=500,
                detail="Audit Log Write Failed - Decision Voided",
            ) from exc

        speed_layer_envelope = {
            **payload_dict,
            "decision": decision_str,
        }
        try:
            serialized = json.dumps(speed_layer_envelope, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            logger.error(
                "speed_layer_serialize_failed",
                exc_info=exc,
            )
        else:
            background_tasks.add_task(_publish_decision_to_speed_layer, serialized)

        background_tasks.add_task(
            _push_lightweight_decision_stream_event,
            payload.entity_id,
            payload.amount,
            decision_str,
        )

        return DecisionResponse(decision=decision_str)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "v1_decide_request",
            entity_id=str(payload.entity_id),
            execution_time_ms=round(elapsed_ms, 3),
            rust_decision=rust_decision,
            database_commit_status=database_commit_status,
        )
