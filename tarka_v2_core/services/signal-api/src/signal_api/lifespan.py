"""Optional FastAPI lifespan wiring for Postgres audit pool + NATS JetStream."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from signal_api.durable_handover import ensure_signals_jetstream_stream
from signal_api.middleware.audit_circuit import AuditPostgresCircuitBreaker
from signal_api.utils.geo_local import LocalGeoIpProvider, build_geo_provider_from_env

logger = logging.getLogger(__name__)


@asynccontextmanager
async def signal_api_resources_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Sets ``app.state.audit_pool`` (asyncpg) when ``SIGNAL_AUDIT_DATABASE_URL`` is set and
    ``app.state.nats_js`` when ``SIGNAL_NATS_URL`` is set. Ensures JetStream stream for ``signals.raw``.
    """
    app.state.audit_circuit = AuditPostgresCircuitBreaker()

    audit_url = (os.environ.get("SIGNAL_AUDIT_DATABASE_URL") or "").strip()
    pool: Any = None
    if audit_url:
        import asyncpg

        pool = await asyncpg.create_pool(audit_url, min_size=1, max_size=10)
        app.state.audit_pool = pool
        logger.info("signal_audit_pool_ready")
    else:
        app.state.audit_pool = None

    nats_url = (os.environ.get("SIGNAL_NATS_URL") or "").strip()
    nc: Any = None
    js: Any = None
    if nats_url:
        import nats

        nc = await nats.connect(nats_url)
        js = nc.jetstream()
        await ensure_signals_jetstream_stream(js)
        app.state.nats_client = nc
        app.state.nats_js = js
        logger.info("signal_nats_jetstream_ready")
    else:
        app.state.nats_client = None
        app.state.nats_js = None

    app.state.geo_provider = build_geo_provider_from_env()

    try:
        yield
    finally:
        gp = getattr(app.state, "geo_provider", None)
        if isinstance(gp, LocalGeoIpProvider):
            gp.close()
        if nc is not None:
            await nc.drain()
            await nc.close()
        if pool is not None:
            await pool.close()
