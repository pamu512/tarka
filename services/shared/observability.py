"""Shared observability: Prometheus metrics, structured logging, trace context.

Usage in any FastAPI service::

    from observability import setup_observability
    setup_observability(app, service_name="decision-api")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ---- Structured JSON logging ----


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            out["exception"] = self.formatException(record.exc_info)
        extra_keys = {"trace_id", "service", "method", "path", "status", "duration_ms"}
        for k in extra_keys:
            if hasattr(record, k):
                out[k] = getattr(record, k)
        return json.dumps(out, default=str)


def setup_logging(service_name: str, level: str = "") -> None:
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ---- Prometheus metrics (lightweight, no external deps) ----


class Metrics:
    """In-process counters and histograms exposed at /metrics in Prometheus text format."""

    def __init__(self, service: str) -> None:
        self.service = service
        self._request_count: dict[str, int] = {}
        self._request_errors: dict[str, int] = {}
        self._latency_sum: dict[str, float] = {}
        self._latency_count: dict[str, int] = {}
        self._custom_counters: dict[str, int] = {}

    def record_request(self, method: str, path: str, status: int, duration: float) -> None:
        key = f"{method}|{path}|{status}"
        self._request_count[key] = self._request_count.get(key, 0) + 1
        lat_key = f"{method}|{path}"
        self._latency_sum[lat_key] = self._latency_sum.get(lat_key, 0.0) + duration
        self._latency_count[lat_key] = self._latency_count.get(lat_key, 0) + 1
        if status >= 500:
            self._request_errors[lat_key] = self._request_errors.get(lat_key, 0) + 1

    def inc(self, name: str, value: int = 1) -> None:
        self._custom_counters[name] = self._custom_counters.get(name, 0) + value

    def request_count_summary(self) -> dict[str, Any]:
        """In-process HTTP counters since boot — for ``GET /v1/slo`` ``current`` (no external TSDB)."""
        total = sum(self._request_count.values())
        errors_5xx = sum(self._request_errors.values())
        return {
            "http_requests_total_observed": total,
            "http_server_errors_total_observed": errors_5xx,
        }

    def to_prometheus(self) -> str:
        lines: list[str] = []
        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        for key, count in sorted(self._request_count.items()):
            method, path, status = key.split("|")
            lines.append(f'http_requests_total{{service="{self.service}",method="{method}",path="{path}",status="{status}"}} {count}')

        lines.append("# HELP http_request_duration_seconds_sum Sum of HTTP request durations")
        lines.append("# TYPE http_request_duration_seconds_sum counter")
        for key, total in sorted(self._latency_sum.items()):
            method, path = key.split("|")
            count = self._latency_count[key]
            lines.append(f'http_request_duration_seconds_sum{{service="{self.service}",method="{method}",path="{path}"}} {total:.6f}')
            lines.append(f'http_request_duration_seconds_count{{service="{self.service}",method="{method}",path="{path}"}} {count}')

        lines.append("# HELP http_server_errors_total Total 5xx errors")
        lines.append("# TYPE http_server_errors_total counter")
        for key, count in sorted(self._request_errors.items()):
            method, path = key.split("|")
            lines.append(f'http_server_errors_total{{service="{self.service}",method="{method}",path="{path}"}} {count}')

        for name, val in sorted(self._custom_counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f'{name}{{service="{self.service}"}} {val}')

        return "\n".join(lines) + "\n"


_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    assert _metrics is not None
    return _metrics


# ---- Middleware ----


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, metrics: Metrics, service: str) -> None:
        super().__init__(app)
        self._metrics = metrics
        self._service = service
        self._log = logging.getLogger(f"{service}.http")

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        trace_id = request.headers.get("x-trace-id", uuid.uuid4().hex[:16])
        request.state.trace_id = trace_id

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        path = request.url.path
        # Normalize path templates for cardinality control
        if "/audit/" in path:
            path = "/v1/audit/{trace_id}"
        if "/cases/" in path and "/comments" in path:
            path = "/v1/cases/{id}/comments"
        if "/cases/" in path and "/labels" in path:
            path = "/v1/cases/{id}/labels"
        if "/cases/" in path and "/graph" in path:
            path = "/v1/cases/{id}/graph"
        if "/entities/" in path and "/tags" in path:
            path = "/v1/entities/{id}/tags"

        self._metrics.record_request(request.method, path, response.status_code, duration)
        response.headers["X-Trace-Id"] = trace_id

        self._log.info(
            "%s %s %d %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            extra={
                "trace_id": trace_id,
                "service": self._service,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        return response


# ---- Setup helper ----


def setup_observability(app: FastAPI, service_name: str) -> Metrics:
    global _metrics
    setup_logging(service_name)
    _metrics = Metrics(service_name)
    app.add_middleware(ObservabilityMiddleware, metrics=_metrics, service=service_name)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        from starlette.responses import PlainTextResponse

        return PlainTextResponse(_metrics.to_prometheus(), media_type="text/plain; charset=utf-8")

    return _metrics
