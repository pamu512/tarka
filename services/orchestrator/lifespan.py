"""FastAPI lifespan: dependency boot, JetStream declarations, and clean shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator_analytics.cloud_provider import CloudAnalytics
from orchestrator_analytics.factory import _normalized_environment, build_analytics_provider
from orchestrator_analytics.hil_context_store import build_hil_context_override_store
from orchestrator_analytics.provider import AnalyticsProvider
from audit_case_worker import build_audit_engine
from deps.v1_api_guard import V1_PROTECTED_ROUTE_DEPENDENCIES, build_v1_rate_limiter
from graph.client import GraphClient, graph_client_from_environment
from messaging.nats_jetstream import (
    JetStreamUnavailableError,
    TarkaEventsJetStreamInitializer,
)
from messaging.shadow_investigate_jetstream import ensure_shadow_investigate_stream
from queues.shadow_dispatch import shadow_investigate_subject
from tarka_shared.database.session import Base

logger = logging.getLogger(__name__)

_CLOUD_ENV_HINTS = frozenset({"production", "prod", "staging", "stage", "cloud"})


@dataclass(frozen=True, slots=True)
class LifespanConfig:
    audit_database_url: str | None
    graph_client_override: GraphClient | None
    analytics_provider: AnalyticsProvider | None
    anumana_redis_client: Any | None
    shadow_dispatch_nats_client: Any | None
    compliance_export_hmac_key: str | bytes | None
    hil_context_override_store_override: Any | None = None


def _clickhouse_configured() -> bool:
    host = (os.environ.get("CLICKHOUSE_HOST") or "").strip()
    url = (os.environ.get("CLICKHOUSE_URL") or "").strip()
    return bool(host or url)


def _clickhouse_required() -> bool:
    return _normalized_environment() in _CLOUD_ENV_HINTS and _clickhouse_configured()


async def _verify_postgres(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("orchestrator_lifespan_postgres_verified")


async def _verify_redis(redis_client: Any) -> None:
    pong = await redis_client.ping()
    if pong is False:
        raise RuntimeError("Redis PING returned false")
    logger.info("orchestrator_lifespan_redis_verified")


def _verify_clickhouse(analytics: AnalyticsProvider) -> None:
    if not isinstance(analytics, CloudAnalytics):
        logger.debug("orchestrator_lifespan_clickhouse_skipped backend=local")
        return
    client = getattr(analytics, "_client", None)
    if client is None:
        if _clickhouse_required():
            raise RuntimeError(
                "ClickHouse is configured (CLICKHOUSE_HOST/CLICKHOUSE_URL) but the client is unavailable",
            )
        logger.warning("orchestrator_lifespan_clickhouse_unconfigured")
        return
    client.command("SELECT 1")
    logger.info("orchestrator_lifespan_clickhouse_verified")


async def _bootstrap_nats_jetstream(
    *,
    nats_client_injected: Any | None,
) -> tuple[Any | None, Any | None]:
    if nats_client_injected is not None:
        logger.info("orchestrator_lifespan_nats_injected skip_jetstream_bootstrap")
        return nats_client_injected, None

    nats_url = (os.environ.get("NATS_URL") or "").strip()
    if not nats_url:
        logger.info("orchestrator_lifespan_nats_skipped NATS_URL unset")
        return None, None

    try:
        import nats  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "NATS_URL is set but nats-py is not installed (pip install tarka-orchestrator[worker])",
        ) from exc

    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    if js is None:
        await nc.drain()
        raise JetStreamUnavailableError("NATS JetStream context is not available on the broker")

    events_init = TarkaEventsJetStreamInitializer.from_environment()
    await events_init.ensure_streams_on(js)
    await ensure_shadow_investigate_stream(js, subject=shadow_investigate_subject())
    logger.info("orchestrator_lifespan_nats_jetstream_verified url=%s", nats_url.split("@")[-1])
    return nc, js


def _flush_logging_handlers() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        try:
            flush = getattr(handler, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            logger.exception("orchestrator_lifespan_log_flush_failed")
    try:
        logging.shutdown()
    except Exception:
        logger.exception("orchestrator_lifespan_logging_shutdown_failed")


def build_lifespan(config: LifespanConfig):
    """Return a FastAPI lifespan context manager for orchestrator dependency wiring."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        audit_engine: AsyncEngine | None = None
        nats_nc: Any | None = None
        nats_js: Any | None = None

        app.state.audit_engine = None
        app.state.audit_session_factory = None
        app.state.graph_client = (
            config.graph_client_override
            if config.graph_client_override is not None
            else graph_client_from_environment()
        )
        if config.analytics_provider is not None:
            app.state.analytics = config.analytics_provider
        else:
            app.state.analytics = build_analytics_provider()

        app.state.anumana_ingest_secret = (
            os.environ.get("ANUMANA_TELEMETRY_INGEST_KEY") or ""
        ).strip() or None
        app.state.anumana_redis_key = (
            os.environ.get("ANUMANA_TELEMETRY_REDIS_KEY") or "anumana:browser_telemetry"
        ).strip()
        app.state.v1_rate_limiter = build_v1_rate_limiter()

        if config.anumana_redis_client is not None:
            app.state.anumana_redis = config.anumana_redis_client
        else:
            aru = (os.environ.get("ANUMANA_REDIS_URL") or "").strip()
            if aru:
                import redis.asyncio as redis_mod  # noqa: PLC0415

                app.state.anumana_redis = redis_mod.from_url(aru, decode_responses=False)
            else:
                app.state.anumana_redis = None

        if config.compliance_export_hmac_key is not None:
            if isinstance(config.compliance_export_hmac_key, bytes):
                app.state.compliance_export_hmac_key = config.compliance_export_hmac_key
            else:
                app.state.compliance_export_hmac_key = (
                    str(config.compliance_export_hmac_key)
                    .strip()
                    .encode(
                        "utf-8",
                    )
                )
        else:
            app.state.compliance_export_hmac_key = (
                (os.environ.get("ORCHESTRATOR_COMPLIANCE_EXPORT_HMAC_KEY") or "")
                .strip()
                .encode("utf-8")
            )

        try:
            if config.audit_database_url:
                import models.cases  # noqa: F401, PLC0415
                import models.decision  # noqa: F401, PLC0415
                import models.normalized_labels  # noqa: F401, PLC0415
                import models.operational_signals  # noqa: F401, PLC0415
                import models.outbox  # noqa: F401, PLC0415
                import tarka_shared.audit_trail  # noqa: F401, PLC0415
                import tarka_shared.engine_rules  # noqa: F401, PLC0415
                import tarka_shared.fraud_rules  # noqa: F401, PLC0415

                audit_engine = build_audit_engine(config.audit_database_url)
                fac = async_sessionmaker(audit_engine, expire_on_commit=False, class_=AsyncSession)
                async with audit_engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                await _verify_postgres(audit_engine)
                app.state.audit_engine = audit_engine
                app.state.audit_session_factory = fac
            else:
                logger.warning("orchestrator_lifespan_postgres_skipped audit_database_url unset")

            redis_client = getattr(app.state, "anumana_redis", None)
            if redis_client is not None and config.anumana_redis_client is None:
                await _verify_redis(redis_client)
            elif redis_client is not None:
                logger.debug("orchestrator_lifespan_redis_injected_skip_ping")

            analytics = getattr(app.state, "analytics", None)
            if analytics is not None:
                await asyncio.to_thread(_verify_clickhouse, analytics)

            if config.hil_context_override_store_override is not None:
                app.state.hil_context_override_store = config.hil_context_override_store_override
            else:
                ch_client = None
                if isinstance(analytics, CloudAnalytics):
                    ch_client = getattr(analytics, "_client", None)
                app.state.hil_context_override_store = build_hil_context_override_store(
                    client_override=ch_client,
                )

            nats_nc, nats_js = await _bootstrap_nats_jetstream(
                nats_client_injected=config.shadow_dispatch_nats_client,
            )
            app.state.shadow_dispatch_nats = nats_nc
            app.state.shadow_dispatch_jetstream = nats_js

            logger.info("orchestrator_lifespan_startup_complete")
            yield
        finally:
            if audit_engine is not None:
                try:
                    await audit_engine.dispose()
                except Exception:
                    logger.exception("orchestrator_lifespan_audit_engine_dispose_failed")
                app.state.audit_engine = None
                app.state.audit_session_factory = None

            if nats_nc is not None and config.shadow_dispatch_nats_client is None:
                try:
                    await nats_nc.drain()
                    await nats_nc.close()
                except Exception:
                    logger.exception("orchestrator_lifespan_nats_close_failed")
            app.state.shadow_dispatch_nats = None
            app.state.shadow_dispatch_jetstream = None

            ar = getattr(app.state, "anumana_redis", None)
            if ar is not None and config.anumana_redis_client is None:
                try:
                    await ar.aclose()
                except Exception:
                    logger.exception("orchestrator_lifespan_anumana_redis_close_failed")
            app.state.anumana_redis = None
            app.state.v1_rate_limiter = None

            dprov = getattr(app.state, "analytics", None)
            if dprov is not None and config.analytics_provider is None:
                try:
                    dprov.close()
                except Exception:
                    logger.exception("orchestrator_lifespan_analytics_close_failed")
            app.state.analytics = None
            app.state.hil_context_override_store = None

            gc = getattr(app.state, "graph_client", None)
            if gc is not None and config.graph_client_override is None:
                try:
                    await gc.close()
                except Exception:
                    logger.exception("orchestrator_lifespan_graph_client_close_failed")
            app.state.graph_client = None

            _flush_logging_handlers()
            logger.info("orchestrator_lifespan_shutdown_complete")

    return lifespan
