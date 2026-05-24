"""
Browser SDK hot-path: ``POST /ingest`` → Redis list (Anumana / Rust drain).

Bypasses JanusGraph / Neo4j and DuckDB append — **LPUSH** + velocity pipeline only.

Payload validation: :class:`~orchestrator.ingestion_schema.IngestionSchema` (fail-closed **400**).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status

from orchestrator.ingestion_schema import IngestionSchema
from orchestrator.anumana_velocity import (
    build_velocity_incr_expire_commands,
    device_hash_token,
    ip_key_token,
    run_ingest_pipeline,
)

logger = logging.getLogger(__name__)


def ingress_client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        return first[:64] if first else None
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


def _canonical_canvas_fp(body: IngestionSchema) -> str | None:
    a = body.canvas_fingerprint or ""
    b = body.canvas_raster_digest_hex or ""
    return (a or b) or None


async def handle_browser_telemetry_ingest(
    request: Request,
    body: IngestionSchema,
    *,
    redis_client: Any | None,
    redis_key: str,
    ingest_secret: str | None,
) -> dict[str, Any]:
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "anumana_redis_unavailable",
                "message": "ANUMANA_REDIS_URL is not set (or test client missing).",
            },
        )
    if ingest_secret:
        header = (
            request.headers.get("x-anumana-ingest-key")
            or request.headers.get("X-Anumana-Ingest-Key")
            or ""
        )
        if not secrets.compare_digest(header, ingest_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "unauthorized"},
            )

    ingress_ip = ingress_client_ip(request)
    canvas = _canonical_canvas_fp(body)
    envelope: dict[str, Any] = {
        "schema": "tarka.browser_telemetry.v1",
        "ts": datetime.now(UTC).isoformat(),
        "ingress_ip": ingress_ip,
        "client_claimed_ip": body.ip,
        "canvas_fingerprint": canvas,
        "canvas_raster_digest_hex": body.canvas_raster_digest_hex,
        "tenant_id": body.tenant_id,
        "device_session_id": body.device_session_id,
        "telemetry_packet": body.telemetry_packet.model_dump() if body.telemetry_packet else None,
    }
    raw = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    ip_segments: list[str] = []
    for ip_raw in (ingress_ip, body.ip):
        if not ip_raw:
            continue
        tok = ip_key_token(ip_raw)
        if tok and tok not in ip_segments:
            ip_segments.append(tok)

    device_token: str | None = None
    if canvas:
        device_token = device_hash_token(canvas)

    vel_cmds = build_velocity_incr_expire_commands(
        tenant_id=body.tenant_id,
        device_token=device_token,
        ip_tokens=ip_segments,
    )

    try:
        await run_ingest_pipeline(
            redis_client,
            stream_key=redis_key,
            payload_bytes=raw,
            velocity_commands=vel_cmds,
            session_watch=(body.tenant_id, body.device_session_id),
        )
    except Exception as exc:
        logger.exception("anumana_redis_pipeline_failed key=%s", redis_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "redis_pipeline_failed", "message": str(exc)},
        ) from exc

    return {
        "accepted": True,
        "sink": "redis",
        "key": redis_key,
        "velocity_updates": len(vel_cmds),
    }
