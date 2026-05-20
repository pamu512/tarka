"""Background worker: replay failed_evidence rows into ClickHouse with anchoring."""

from __future__ import annotations

import logging

import anyio
import asyncpg
import redis.asyncio as redis
from clickhouse_connect.driver.client import Client as ClickHouseClient
from clickhouse_connect.driver.exceptions import ClickHouseError

from ingestor.batch_anchor import append_manifest_and_maybe_finalize
from ingestor.clickhouse_sink import (
    create_client,
    insert_audit_anchor,
    insert_evidence_manifest,
)
from ingestor.failed_evidence_store import (
    create_pool,
    fetch_pending_batch,
    mark_replay_failure,
    mark_replayed,
)
from ingestor.manifest_row import ManifestDecodeError, decode_manifest_row
from ingestor.manifest_schema import (
    SchemaIncompatibilityError,
    assert_ingestor_descriptor_matches_pin,
)
from ingestor.settings import IngestorSettings

logger = logging.getLogger(__name__)


async def _after_manifest_insert(
    redis_client: redis.Redis,
    settings: IngestorSettings,
    ch: ClickHouseClient,
    row: dict[str, object],
) -> None:
    """Mirror arq_worker: append to Redis batch and persist audit anchor when a batch seals."""
    anchor = await append_manifest_and_maybe_finalize(
        redis_client,
        settings,
        tenant_id=str(row["tenant_id"]),
        manifest_id=row["manifest_id"],
        raw_sha256=bytes(row["raw_manifest_sha256"]),
    )
    if anchor is None:
        return
    await anyio.to_thread(
        insert_audit_anchor,
        ch,
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


async def _process_row(
    *,
    pool: asyncpg.Pool,
    redis_client: redis.Redis,
    settings: IngestorSettings,
    ch: ClickHouseClient,
    row: asyncpg.Record,
) -> None:
    row_id = int(row["id"])
    raw: bytes = row["raw_manifest"]
    try:
        decoded = decode_manifest_row(raw, settings=settings)
    except ManifestDecodeError as exc:
        await mark_replay_failure(
            pool,
            row_id,
            error=f"manifest_decode_failed:{exc}",
            max_attempts=settings.replay_abandon_after_attempts,
        )
        logger.warning(
            "replay skipped: invalid protobuf",
            extra={"failed_evidence_id": row_id},
        )
        return
    except SchemaIncompatibilityError as exc:
        await mark_replay_failure(
            pool,
            row_id,
            error=f"manifest_schema_incompatible:{exc.detail}:{exc}",
            max_attempts=settings.replay_abandon_after_attempts,
        )
        logger.warning(
            "replay skipped: schema incompatible",
            extra={"failed_evidence_id": row_id, "detail": exc.detail},
        )
        return

    try:
        await anyio.to_thread(insert_evidence_manifest, ch, settings, decoded)
    except (ClickHouseError, TimeoutError, OSError) as exc:
        await mark_replay_failure(
            pool,
            row_id,
            error=f"{type(exc).__name__}:{exc}",
            max_attempts=settings.replay_abandon_after_attempts,
        )
        logger.warning(
            "replay ClickHouse insert failed",
            extra={"failed_evidence_id": row_id},
            exc_info=exc,
        )
        return

    try:
        await _after_manifest_insert(redis_client, settings, ch, decoded)
    except (ClickHouseError, TimeoutError, OSError) as exc:
        await mark_replay_failure(
            pool,
            row_id,
            error=f"anchor_or_batch:{type(exc).__name__}:{exc}",
            max_attempts=settings.replay_abandon_after_attempts,
        )
        logger.exception(
            "replay succeeded for manifest but anchor path failed",
            extra={"failed_evidence_id": row_id},
        )
        return

    await mark_replayed(pool, row_id)
    logger.info(
        "replayed failed_evidence row",
        extra={"failed_evidence_id": row_id, "manifest_id": str(decoded["manifest_id"])},
    )


async def replay_main() -> None:
    settings = IngestorSettings()
    assert_ingestor_descriptor_matches_pin(settings)
    if not settings.postgres_dsn.strip():
        raise SystemExit(
            "TARKA_INGESTOR_POSTGRES_DSN must be set for the replay worker (failed_evidence store)."
        )

    pool = await create_pool(settings)
    redis_client = redis.from_url(
        str(settings.redis_dsn),
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_s,
        socket_timeout=settings.redis_socket_timeout_s,
    )
    ch = create_client(settings)
    try:
        while True:
            while True:
                rows = await fetch_pending_batch(pool, limit=settings.replay_batch_size)
                if not rows:
                    break
                for row in rows:
                    await _process_row(
                        pool=pool,
                        redis_client=redis_client,
                        settings=settings,
                        ch=ch,
                        row=row,
                    )
            await anyio.sleep(settings.replay_interval_seconds)
    finally:
        ch.close()
        await redis_client.aclose()
        await pool.close()


def run_replay_worker() -> None:
    logging.basicConfig(level=logging.INFO)
    anyio.run(replay_main)


if __name__ == "__main__":
    run_replay_worker()
