"""Arq worker: async offload path for ClickHouse writes + batch anchoring."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import Any

import redis.asyncio as redis
from arq.connections import RedisSettings
from clickhouse_connect.driver.exceptions import ClickHouseError

from ingestor.batch_anchor import append_manifest_and_maybe_finalize
from ingestor.clickhouse_sink import create_client, insert_audit_anchor, insert_evidence_manifest
from ingestor.failed_evidence_store import create_pool, insert_failed_manifest
from ingestor.manifest_row import ManifestDecodeError, decode_manifest_row
from ingestor.manifest_schema import (
    SchemaIncompatibilityError,
    assert_ingestor_descriptor_matches_pin,
)
from ingestor.settings import IngestorSettings

logger = logging.getLogger(__name__)

_settings_snapshot = IngestorSettings()


async def startup(ctx: dict[str, Any]) -> None:
    settings = IngestorSettings()
    ctx["settings"] = settings
    assert_ingestor_descriptor_matches_pin(settings)
    ctx["ch"] = create_client(settings)
    ctx["redis_anchor"] = redis.from_url(
        str(settings.redis_dsn),
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_s,
        socket_timeout=settings.redis_socket_timeout_s,
    )
    ctx["pg"] = None
    if settings.postgres_dsn.strip():
        ctx["pg"] = await create_pool(settings)
    else:
        logger.warning(
            "TARKA_INGESTOR_POSTGRES_DSN is empty; ClickHouse failures will fall back to Redis DLQ only",
        )


async def shutdown(ctx: dict[str, Any]) -> None:
    ch = ctx.get("ch")
    if ch is not None:
        ch.close()
    pg = ctx.get("pg")
    if pg is not None:
        await pg.close()
    r = ctx.get("redis_anchor")
    if r is not None:
        await r.aclose()


async def _park_failed_clickhouse_insert(
    ctx: dict[str, Any],
    settings: IngestorSettings,
    *,
    raw: bytes,
    manifest_b64: str,
    detail: str,
    manifest_id: str,
) -> None:
    """Persist to Postgres failed_evidence; on failure push JSON payload to Redis."""
    redis_client = ctx["redis_anchor"]
    payload = json.dumps(
        {
            "error": "clickhouse_insert_exhausted",
            "detail": detail,
            "manifest_b64": manifest_b64,
        },
        separators=(",", ":"),
    )
    pg_pool = ctx.get("pg")
    if pg_pool is not None:
        try:
            row_id = await insert_failed_manifest(
                pg_pool,
                raw_manifest=raw,
                manifest_b64=manifest_b64,
                last_error=detail,
                failure_phase="clickhouse_insert",
            )
            logger.warning(
                "manifest parked on Postgres failed_evidence after ClickHouse retries exhausted",
                extra={
                    "failed_evidence_id": row_id,
                    "manifest_id": manifest_id,
                },
            )
            return
        except Exception:
            logger.exception(
                "Postgres failed_evidence insert failed; parking on Redis DLQ",
                extra={"manifest_id": manifest_id},
            )
    await redis_client.rpush(settings.redis_dlq_clickhouse_key, payload)
    logger.error(
        "manifest parked on Redis after ClickHouse failure (Postgres unavailable or insert failed)",
        extra={
            "redis_dlq_key": settings.redis_dlq_clickhouse_key,
            "manifest_id": manifest_id,
        },
    )


async def sink_manifest(ctx: dict[str, Any], manifest_b64: str) -> None:
    """Decode protobuf from Base64, persist row, and finalize anchors every BATCH_SIZE manifests."""
    settings: IngestorSettings = ctx["settings"]

    try:
        raw = base64.b64decode(manifest_b64, validate=True)
    except binascii.Error as exc:
        logger.error(
            "ingest job rejected: invalid base64 payload",
            extra={"reason": "invalid_base64"},
            exc_info=exc,
        )
        raise ValueError("manifest payload must be valid base64") from exc

    try:
        row = decode_manifest_row(raw, settings=settings)
    except ManifestDecodeError as exc:
        dlq = ctx["redis_anchor"]
        payload = json.dumps(
            {
                "error": "manifest_decode_failed",
                "detail": str(exc),
                "manifest_b64": manifest_b64,
            },
            separators=(",", ":"),
        )
        await dlq.rpush(settings.redis_dlq_key, payload)
        logger.error(
            "manifest decode failed; payload parked on redis DLQ",
            extra={"redis_dlq_key": settings.redis_dlq_key},
            exc_info=exc,
        )
        return
    except SchemaIncompatibilityError as exc:
        dlq = ctx["redis_anchor"]
        payload = json.dumps(
            {
                "error": "manifest_schema_incompatible",
                "detail": exc.detail,
                "message": str(exc),
                "manifest_b64": manifest_b64,
            },
            separators=(",", ":"),
        )
        await dlq.rpush(settings.redis_dlq_schema_key, payload)
        logger.error(
            "manifest rejected by schema registry",
            extra={
                "redis_dlq_key": settings.redis_dlq_schema_key,
                "schema_detail": exc.detail,
            },
            exc_info=exc,
        )
        return

    try:
        await asyncio.to_thread(insert_evidence_manifest, ctx["ch"], settings, row)
    except (ClickHouseError, TimeoutError, OSError) as exc:
        detail = f"{type(exc).__name__}:{exc}"
        logger.exception(
            "clickhouse evidence insert failed after retries; sending to DLQ",
            extra={"manifest_id": str(row["manifest_id"])},
        )
        await _park_failed_clickhouse_insert(
            ctx,
            settings,
            raw=raw,
            manifest_b64=manifest_b64,
            detail=detail,
            manifest_id=str(row["manifest_id"]),
        )
        return

    anchor = await append_manifest_and_maybe_finalize(
        ctx["redis_anchor"],
        settings,
        tenant_id=str(row["tenant_id"]),
        manifest_id=row["manifest_id"],
        raw_sha256=bytes(row["raw_manifest_sha256"]),
    )
    if anchor is None:
        return

    try:
        await asyncio.to_thread(
            insert_audit_anchor,
            ctx["ch"],
            settings,
            str(row["tenant_id"]),
            anchor["batch_seq"],
            anchor["batch_root_hex"],
            anchor["manifest_count"],
            anchor["first_manifest_id"],
            anchor["last_manifest_id"],
            anchor["first_leaf_sha256_hex"],
            anchor["last_leaf_sha256_hex"],
        )
    except (ClickHouseError, TimeoutError, OSError):
        logger.exception(
            "clickhouse audit anchor insert failed after retries",
            extra={"batch_seq": anchor["batch_seq"]},
        )
        raise


class WorkerSettings:
    """Imported by `arq ingestor.arq_worker.WorkerSettings` CLI."""

    redis_settings = RedisSettings.from_dsn(str(_settings_snapshot.redis_dsn))
    functions = [sink_manifest]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = _settings_snapshot.arq_max_tries
