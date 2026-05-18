from __future__ import annotations

import logging
import os
import random
from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger(__name__)


def _traceparent_header() -> str:
    trace_id = f"{random.getrandbits(128):032x}"
    span_id = f"{random.getrandbits(64):016x}"
    return f"00-{trace_id}-{span_id}-01"


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # type: ignore[override]
        traceparent = request.headers.get("traceparent") or _traceparent_header()
        request.state.traceparent = traceparent
        resp = await call_next(request)
        resp.headers["traceparent"] = traceparent
        return resp


def setup_tracing(app: FastAPI, service_name: str) -> None:
    """Best-effort distributed tracing setup.

    - Always injects/propagates `traceparent` via lightweight middleware.
    - Optionally enables OpenTelemetry FastAPI instrumentation when installed.
    """
    app.add_middleware(TraceContextMiddleware)

    if os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
    except Exception:
        log.info(
            "OpenTelemetry not installed; running with traceparent middleware only (%s)",
            service_name,
        )
        return

    try:
        FastAPIInstrumentor.instrument_app(app)
        log.info("OpenTelemetry FastAPI instrumentation enabled (%s)", service_name)
    except Exception as exc:
        log.warning("OpenTelemetry instrumentation failed (%s): %s", service_name, exc)
