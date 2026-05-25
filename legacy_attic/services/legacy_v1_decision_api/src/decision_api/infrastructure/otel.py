"""OpenTelemetry: OTLP/gRPC traces, FastAPI HTTP spans, and redis-py / redis.asyncio spans.

Redis ``GET`` / ``SET`` / ``SETEX`` / ``EVAL`` (Lua merge) calls made during ``POST /v1/decisions/evaluate``
run under the active request span from :class:`opentelemetry.instrumentation.fastapi.FastAPIInstrumentor`,
so fraud signature traffic (``fraud:*`` keys in :mod:`decision_api.redis_store`) is recorded as child spans
of the decision request when ``OTEL_SDK_DISABLED`` is unset.

Call :func:`init_opentelemetry` once after :class:`fastapi.FastAPI` construction and **before**
:func:`redis.asyncio.from_url` (i.e. before :meth:`decision_api.redis_store.RedisTags.connect` in lifespan).
"""

from __future__ import annotations

import logging
import os
from typing import Final
from urllib.parse import urlparse

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

DEFAULT_OTEL_SERVICE_NAME: Final[str] = "decision-api"

_INITIALIZED: bool = False
_INIT_ATTEMPTED: bool = False
_redis_instrumentor: RedisInstrumentor | None = None


class OtelConfigurationError(ValueError):
    """Raised for invalid OTLP settings or a second ``init_opentelemetry`` call in one process."""


def _service_name() -> str:
    raw = (os.environ.get("OTEL_SERVICE_NAME") or "").strip()
    return raw if raw else DEFAULT_OTEL_SERVICE_NAME


def _otlp_grpc_endpoint() -> str | None:
    traces = (os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or "").strip()
    if traces:
        return traces
    general = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    return general or None


def _validate_endpoint(url: str) -> None:
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        raise OtelConfigurationError(
            f"Unsupported OTLP endpoint scheme {parsed.scheme!r}; expected http or https."
        )


def init_opentelemetry(*fastapi_apps: FastAPI) -> None:
    """Install OTLP tracing, instrument FastAPI, and patch redis for async/sync clients.

    Honors ``OTEL_SDK_DISABLED``. When enabled, :class:`RedisInstrumentor` runs **before** any
    ``redis.asyncio`` client is constructed so ``GET``/``SET``/Lua paths emit spans under the HTTP span.
    """
    global _INITIALIZED, _INIT_ATTEMPTED, _redis_instrumentor

    if not fastapi_apps:
        raise OtelConfigurationError(
            "init_opentelemetry() requires at least one FastAPI application"
        )

    if _INIT_ATTEMPTED:
        raise OtelConfigurationError(
            "init_opentelemetry() was already called in this process"
        )
    _INIT_ATTEMPTED = True

    disabled = (os.environ.get("OTEL_SDK_DISABLED") or "").strip().lower()
    if disabled in ("1", "true", "yes", "on"):
        logger.warning("OpenTelemetry disabled via OTEL_SDK_DISABLED")
        return

    endpoint = _otlp_grpc_endpoint()
    if endpoint is not None:
        _validate_endpoint(endpoint)

    service_name = _service_name()
    resource = Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPSpanExporter(endpoint=endpoint, timeout=None)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    for app in fastapi_apps:
        FastAPIInstrumentor.instrument_app(app)

    _redis_instrumentor = RedisInstrumentor()
    _redis_instrumentor.instrument()

    _INITIALIZED = True
    logger.info(
        "OpenTelemetry initialized (OTLP gRPC + FastAPI + Redis): service.name=%r endpoint=%r",
        service_name,
        endpoint or "(env default)",
    )


def shutdown_opentelemetry() -> None:
    """Flush tracer export, remove Redis instrumentation, and reset the global tracer provider."""
    global _INITIALIZED, _redis_instrumentor

    if not _INITIALIZED:
        if _redis_instrumentor is not None:
            try:
                _redis_instrumentor.uninstrument()
            except Exception as exc:
                logger.warning(
                    "Redis OpenTelemetry uninstrument failed: %s", exc, exc_info=True
                )
            _redis_instrumentor = None
        return

    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()

    if _redis_instrumentor is not None:
        try:
            _redis_instrumentor.uninstrument()
        except Exception as exc:
            logger.warning(
                "Redis OpenTelemetry uninstrument failed: %s", exc, exc_info=True
            )
        _redis_instrumentor = None

    trace.set_tracer_provider(trace.NoOpTracerProvider())
    _INITIALIZED = False
