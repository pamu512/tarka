"""Enqueue EvidenceManifest bytes onto the Arq sink queue (non-blocking for callers)."""

from __future__ import annotations

import asyncio
import base64
import logging
import random

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.exceptions import RedisError

from ingestor.settings import IngestorSettings

logger = logging.getLogger(__name__)


async def enqueue_manifest_bytes(
    raw_manifest: bytes,
    *,
    settings: IngestorSettings | None = None,
    pool: ArqRedis | None = None,
) -> None:
    """Schedule asynchronous persistence using Arq + Redis.

    Callers on a hot path should create one ``ArqRedis`` pool at process startup and pass it via
    ``pool=`` to avoid per-call connection setup latency.
    """
    if not raw_manifest:
        raise ValueError("raw_manifest must be non-empty")

    cfg = settings or IngestorSettings()
    payload = base64.b64encode(raw_manifest).decode("ascii")
    redis_settings = RedisSettings.from_dsn(str(cfg.redis_dsn))

    attempts = 4
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        own_pool = pool is None
        active_pool: ArqRedis | None = None
        try:
            active_pool = pool if pool is not None else await create_pool(redis_settings)
            job = await active_pool.enqueue_job("sink_manifest", payload)
            logger.debug(
                "enqueued manifest ingest job",
                extra={"job_id": getattr(job, "job_id", None)},
            )
            return
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            last_exc = exc
            logger.warning(
                "enqueue retry scheduled",
                extra={"attempt": attempt + 1, "max_attempts": attempts},
                exc_info=exc,
            )
            if attempt + 1 >= attempts:
                break
            backoff = min(2.0, 0.05 * (2**attempt))
            jitter = random.uniform(0.0, 0.05)
            await asyncio.sleep(backoff + jitter)
        finally:
            if own_pool and active_pool is not None:
                await active_pool.aclose()

    assert last_exc is not None
    logger.error(
        "enqueue exhausted retries",
        extra={"attempts": attempts},
        exc_info=last_exc,
    )
    raise last_exc
