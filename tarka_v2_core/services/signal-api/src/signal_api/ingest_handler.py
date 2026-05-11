"""
Fast-path **UnifiedSignalSchema** ingestion: Redis session dedup + atomic velocity counters.

**Durable intent handover** (when configured):

* **Postgres** ``audit_logs``: append-only row with ``raw_payload``, ``integrity_signature`` (HMAC-SHA256
  of canonical signal JSON via ``SYSTEM_SECRET``), dispatched via **FastAPI ``BackgroundTasks``** so the
  HTTP response is not blocked.
* **NATS JetStream**: publish canonical signal bytes to ``signals.raw`` for downstream JanusGraph / DuckDB.

Environment:

* ``SYSTEM_SECRET`` — required when ``app.state.audit_pool`` is set (from ``SIGNAL_AUDIT_DATABASE_URL``).
* ``SIGNAL_AUDIT_DATABASE_URL`` — optional asyncpg pool (see :mod:`signal_api.lifespan`).
* ``SIGNAL_NATS_URL`` — optional; JetStream publish to ``signals.raw`` (stream ``SIGNALS`` by default).

**Audit Postgres circuit** (see :mod:`signal_api.middleware.audit_circuit`): ``SIGNAL_AUDIT_EXECUTE_TIMEOUT_SEC`` (default
``5``, ``<= 0`` disables ``wait_for``), ``SIGNAL_AUDIT_CIRCUIT_OPEN_AFTER_TIMEOUTS`` (default ``5``),
``SIGNAL_AUDIT_CIRCUIT_DEGRADED_SEC`` (default ``60``). Five consecutive audit **timeouts** → **degraded mode** (no
Postgres audit write; Redis ingest + NATS unchanged). Responses may include ``X-Signal-Audit-Degraded: 1``.

**Dedup**: ``SET seen:{session_id} NX`` — replays return **204** (no audit/NATS/velocity updates).

**Velocity** (first-seen only): ``INCR`` + ``EXPIRE`` for ``velocity:ip:{ip}:1m`` and ``velocity:device:{canvas_hash}:5m``.

**Hiredis**: ``redis[hiredis]`` for parser throughput.

**In-transit integrity** (optional ``n`` + ``ih`` on :class:`~tarka_v2_core.schemas.ingestion.UnifiedSignalSchema`):
server recomputes SHA-256 over canonical JSON (excluding ``n``/``ih``) + ``|`` + nonce and compares to ``ih``.
Mint nonces via ``POST /v1/session/nonce``. Mismatch → Postgres ``decision`` = ``TAMPERED_IN_TRANSIT`` (see :mod:`signal_api.transit_integrity`).

**GeoIP** (see :mod:`signal_api.utils.geo_local`): after transit verification, ``client_ip`` is resolved with an
in-memory MaxMind MMDB (``SIGNAL_GEOIP_MMDB`` / ``GEOIP_MMDB_PATH``); ``gc`` / ``gct`` are appended before audit/NATS
canonicalization.

**Degraded-mode header**: register ``AuditDegradedModeHeaderMiddleware`` on the FastAPI app
(``app.add_middleware(AuditDegradedModeHeaderMiddleware)`` from :mod:`signal_api.middleware.audit_circuit`) if you want
``X-Signal-Audit-Degraded`` on HTTP responses when the audit circuit is open.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from redis.asyncio import Redis

from signal_api.durable_handover import (
    canonical_signal_json_bytes,
    durable_intent_handover,
    integrity_hmac_sha256_hex,
)
from signal_api.middleware.audit_circuit import AuditPostgresCircuitBreaker
from signal_api.transit_integrity import transit_audit_decision, verify_in_transit_integrity
from signal_api.utils.geo_local import build_geo_provider_from_env
from starlette.requests import Request
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Ingest"])

_SEEN_PREFIX = "seen:"
_DEFAULT_SEEN_TTL = 86_400


def _seen_ttl_sec() -> int:
    raw = os.environ.get("SIGNAL_INGEST_SEEN_TTL_SEC", "").strip()
    if not raw:
        return _DEFAULT_SEEN_TTL
    return max(60, min(int(raw), 86_400 * 30))


def velocity_ip_1m_key(client_ip: str) -> str:
    return f"velocity:ip:{client_ip}:1m"


def velocity_device_5m_key(canvas_hash: str) -> str:
    return f"velocity:device:{canvas_hash}:5m"


def build_async_redis(url: str) -> Redis:
    """
    Async Redis client. With ``redis[hiredis]`` installed, redis-py uses **Hiredis** for parsing
    (see redis connection ``protocol`` / parser selection in redis-py 5.x).
    """
    return Redis.from_url(
        url,
        decode_responses=True,
        health_check_interval=30,
    )


async def get_redis(request: Request) -> Redis:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise RuntimeError("app.state.redis is not configured")
    return r


@router.post(
    "/ingest",
    status_code=status.HTTP_201_CREATED,
    summary="Ingest unified browser signals (Redis fast path)",
)
async def ingest_unified_signals(
    request: Request,
    background_tasks: BackgroundTasks,
    body: UnifiedSignalSchema,
    redis: Annotated[Redis, Depends(get_redis)],
) -> Response:
    sid = str(body.session_id)
    seen_key = f"{_SEEN_PREFIX}{sid}"
    ttl = _seen_ttl_sec()

    first_seen = await redis.set(seen_key, "1", nx=True, ex=ttl)
    if first_seen is not True:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    ip_s = str(body.client_ip)
    ch = body.canvas_hash
    ip_key = velocity_ip_1m_key(ip_s)
    dev_key = velocity_device_5m_key(ch)

    pipe: Any = redis.pipeline(transaction=False)
    pipe.incr(ip_key)
    pipe.expire(ip_key, int(os.environ.get("SIGNAL_INGEST_VEL_IP_TTL_SEC", "180")))
    pipe.incr(dev_key)
    pipe.expire(dev_key, int(os.environ.get("SIGNAL_INGEST_VEL_DEVICE_TTL_SEC", "900")))
    await pipe.execute()

    logger.info(
        "signal_ingest_accepted session_id=%s ip_key=%s device_key=%s",
        sid,
        ip_key,
        dev_key,
    )

    transit_ok = await verify_in_transit_integrity(redis, body)
    audit_decision = transit_audit_decision(transit_ok)

    geo = getattr(request.app.state, "geo_provider", None) or build_geo_provider_from_env()
    request.app.state.geo_provider = geo
    body = geo.enrich_unified_signal(body)

    canonical_bytes = canonical_signal_json_bytes(body)
    audit_pool = getattr(request.app.state, "audit_pool", None)
    js = getattr(request.app.state, "nats_js", None)

    if audit_pool is None and js is None:
        return Response(status_code=status.HTTP_201_CREATED)

    secret = (os.environ.get("SYSTEM_SECRET") or "").strip()
    if audit_pool is not None and not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "audit_misconfigured",
                "message": "SYSTEM_SECRET is required when Postgres audit pool is configured",
            },
        )

    integrity_hex = integrity_hmac_sha256_hex(secret, canonical_bytes) if audit_pool else ""

    circuit = getattr(request.app.state, "audit_circuit", None)
    if audit_pool is not None and circuit is None:
        circuit = AuditPostgresCircuitBreaker()
        request.app.state.audit_circuit = circuit

    background_tasks.add_task(
        durable_intent_handover,
        pool=audit_pool,
        js=js,
        body=body,
        canonical_bytes=canonical_bytes,
        integrity_hex=integrity_hex,
        audit_decision=audit_decision,
        circuit=circuit,
    )
    return Response(status_code=status.HTTP_201_CREATED)
