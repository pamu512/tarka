"""Shared observability: Prometheus metrics, structlog JSON logging, trace context.

Usage in any FastAPI service::

    from observability import setup_observability
    setup_observability(app, service_name="decision-api")

Optional error reporting (when ``SENTRY_DSN`` or ``TARKA_SENTRY_DSN`` is set)::

    from observability import setup_sentry_sdk
    setup_sentry_sdk(service_name="decision-api")  # before ``setup_observability``

When ``TARKA_LOKI_PUSH_URL`` or ``LOKI_PUSH_URL`` is set (for example in the Nix devshell),
structured JSON logs are also POSTed to Grafana Loki with retries and backpressure.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

from loki_push import attach_loki_logging_if_configured


def _ensure_trace_triplet(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Guarantee correlation keys on every emitted record (ELK / Loki / Sentry)."""
    event_dict.setdefault("trace_id", "")
    event_dict.setdefault("rule_set_hash", "")
    event_dict.setdefault("tenant_id", "")
    event_dict.setdefault("otel_trace_id", "")
    return event_dict


def _bind_service_name(service: str):
    def processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        return event_dict

    return processor


class _PassthroughRustJsonFormatter(logging.Formatter):
    """Rust rule-engine bridge emits one JSON object per line; avoid double-encoding."""

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self._inner = inner

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if msg.startswith("{") and '"trace_id"' in msg:
            try:
                parsed = json.loads(msg)
            except json.JSONDecodeError:
                return self._inner.format(record)
            if isinstance(parsed, dict):
                for key in ("trace_id", "rule_set_hash", "tenant_id", "otel_trace_id"):
                    parsed.setdefault(key, getattr(record, key, "") or "")
                return json.dumps(parsed, default=str)
        return self._inner.format(record)


def setup_logging(service_name: str, level: str = "") -> None:
    log_level = getattr(logging, (level or os.environ.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)

    shared_pre = [
        structlog.stdlib.filter_by_level,
        merge_contextvars,
        _ensure_trace_triplet,
        _bind_service_name(service_name),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso", key="ts", utc=True),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=shared_pre + [structlog.stdlib.render_to_log_kwargs],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    foreign_pre = [
        merge_contextvars,
        _ensure_trace_triplet,
        _bind_service_name(service_name),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso", key="ts", utc=True),
        structlog.processors.UnicodeDecoder(),
    ]

    inner = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=foreign_pre,
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    passthrough = _PassthroughRustJsonFormatter(inner)
    handler.setFormatter(passthrough)
    root.addHandler(handler)
    root.setLevel(log_level)

    attach_loki_logging_if_configured(
        service_name=service_name,
        json_formatter=passthrough,
        root=root,
    )

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def sync_rule_engine_tracing_bridge() -> None:
    """Mirror contextvars into the optional Rust rule-engine TLS sink (same-thread calls)."""
    try:
        from tarka_rule_engine import set_tracing_log_context  # type: ignore[import-not-found]
    except ImportError:
        return
    ctx = structlog.contextvars.get_contextvars()
    set_tracing_log_context(
        str(ctx.get("trace_id") or ""),
        str(ctx.get("rule_set_hash") or ""),
        str(ctx.get("tenant_id") or ""),
        str(ctx.get("otel_trace_id") or ""),
    )


def _parse_w3c_trace_id_from_traceparent(header: str | None) -> str:
    """Return lowercase 32-hex trace id from W3C ``traceparent``, or ``\"\"``."""
    if not header:
        return ""
    parts = header.strip().split("-")
    if len(parts) >= 2 and len(parts[1]) == 32:
        tid = parts[1]
        if all(c in "0123456789abcdefABCDEF" for c in tid):
            return tid.lower()
    return ""


_SENTRY_INITIALIZED = False


def setup_sentry_sdk(service_name: str) -> None:
    """Initialize Sentry when ``SENTRY_DSN`` or ``TARKA_SENTRY_DSN`` is set.

    Tags each HTTP request with ``trace_id`` (API correlation) and ``otel_trace_id``
    (W3C / Evidence Manifest ``otel_trace_id`` on spans) once :class:`ObservabilityMiddleware`
    binds context — see ``before_send_transaction`` / scope updates in middleware for live tags.

    Safe to call once per process; subsequent calls are ignored.
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return

    dsn = (os.environ.get("SENTRY_DSN") or os.environ.get("TARKA_SENTRY_DSN") or "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logging.getLogger(__name__).warning(
            "sentry_sdk not installed; skipping Sentry initialization"
        )
        return

    traces_sample_raw = (os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or "").strip()
    traces_sample = float(traces_sample_raw) if traces_sample_raw else 0.0
    if traces_sample < 0.0:
        traces_sample = 0.0
    if traces_sample > 1.0:
        traces_sample = 1.0

    def _enrich_event_with_trace_context(event: dict[str, Any]) -> None:
        """Attach log correlation from structlog contextvars."""
        ctx = structlog.contextvars.get_contextvars()
        tid = str(ctx.get("trace_id") or "").strip()
        otel = str(ctx.get("otel_trace_id") or "").strip()
        tags = event.setdefault("tags", {})
        if isinstance(tags, dict):
            if tid:
                tags.setdefault("trace_id", tid)
            if otel:
                tags.setdefault("otel_trace_id", otel)
        contexts = event.setdefault("contexts", {})
        if otel and isinstance(contexts, dict):
            ev_ctx = contexts.setdefault("tarka_evidence", {})
            if isinstance(ev_ctx, dict):
                ev_ctx.setdefault("otel_trace_id", otel)

    def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
        try:
            _enrich_event_with_trace_context(event)
        except Exception:
            logging.getLogger(__name__).debug(
                "sentry_before_send_context_failed", exc_info=True
            )
        return event

    def _before_send_transaction(
        event: dict[str, Any], hint: dict[str, Any]
    ) -> dict[str, Any] | None:
        try:
            _enrich_event_with_trace_context(event)
        except Exception:
            logging.getLogger(__name__).debug(
                "sentry_before_send_transaction_context_failed", exc_info=True
            )
        return event

    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                StarletteIntegration(transaction_style="endpoint"),
                FastApiIntegration(transaction_style="endpoint"),
            ],
            traces_sample_rate=traces_sample,
            environment=(os.environ.get("SENTRY_ENVIRONMENT") or "").strip() or None,
            release=(os.environ.get("SENTRY_RELEASE") or "").strip() or None,
            before_send=_before_send,
            before_send_transaction=_before_send_transaction,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "sentry_sdk init failed: %s", exc, exc_info=True
        )
        return
    _SENTRY_INITIALIZED = True
    logging.getLogger(__name__).info(
        "sentry_sdk initialized for service=%s traces_sample_rate=%s",
        service_name,
        traces_sample,
    )


def _bind_sentry_http_scope(trace_id: str, otel_trace_id: str) -> None:
    """Apply correlation tags to the active Sentry scope (HTTP request thread/task)."""
    if not _SENTRY_INITIALIZED:
        return
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        scope = sentry_sdk.get_current_scope()
        scope.set_tag("trace_id", trace_id)
        if otel_trace_id:
            scope.set_tag("otel_trace_id", otel_trace_id)
            scope.set_context(
                "tarka_evidence",
                {"otel_trace_id": otel_trace_id},
            )
    except Exception:
        logging.getLogger(__name__).debug(
            "sentry_scope_bind_failed", exc_info=True
        )


# ---- Prometheus metrics (lightweight, no external deps) ----


class Metrics:
    """In-process counters and histograms exposed at /metrics in Prometheus text format."""

    def __init__(self, service: str) -> None:
        self.service = service
        # Key: method|path|status|tenant_query — tenant_query is present|absent (query param only; R1.4)
        self._request_count: dict[str, int] = {}
        self._latency_sum: dict[str, float] = {}
        self._latency_count: dict[str, int] = {}
        # 5xx / 4xx by route + tenant_query (no raw tenant id — cardinality-safe)
        self._server_errors: dict[str, int] = {}
        self._client_errors: dict[str, int] = {}
        self._custom_counters: dict[str, int] = {}

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration: float,
        *,
        tenant_query_scope: str = "absent",
    ) -> None:
        tq = tenant_query_scope if tenant_query_scope in ("present", "absent") else "absent"
        req_key = f"{method}|{path}|{status}|{tq}"
        self._request_count[req_key] = self._request_count.get(req_key, 0) + 1
        lat_key = f"{method}|{path}"
        self._latency_sum[lat_key] = self._latency_sum.get(lat_key, 0.0) + duration
        self._latency_count[lat_key] = self._latency_count.get(lat_key, 0) + 1
        err_key = f"{method}|{path}|{tq}"
        if 400 <= status < 500:
            self._client_errors[err_key] = self._client_errors.get(err_key, 0) + 1
        elif status >= 500:
            self._server_errors[err_key] = self._server_errors.get(err_key, 0) + 1

    def inc(self, name: str, value: int = 1) -> None:
        self._custom_counters[name] = self._custom_counters.get(name, 0) + value

    def request_count_summary(self) -> dict[str, Any]:
        """In-process HTTP counters since boot — for ``GET /v1/slo`` ``current`` (no external TSDB)."""
        total = sum(self._request_count.values())
        errors_5xx = sum(self._server_errors.values())
        errors_4xx = sum(self._client_errors.values())
        return {
            "http_requests_total_observed": total,
            "http_server_errors_total_observed": errors_5xx,
            "http_client_errors_total_observed": errors_4xx,
        }

    def to_prometheus(self) -> str:
        lines: list[str] = []
        lines.append("# HELP http_requests_total Total HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        for key, count in sorted(self._request_count.items()):
            method, path, status, tq = key.split("|", 3)
            lines.append(
                f'http_requests_total{{service="{self.service}",method="{method}",path="{path}",status="{status}",tenant_query="{tq}"}} {count}'
            )

        lines.append("# HELP http_request_duration_seconds_sum Sum of HTTP request durations")
        lines.append("# TYPE http_request_duration_seconds_sum counter")
        for key, total in sorted(self._latency_sum.items()):
            method, path = key.split("|")
            count = self._latency_count[key]
            lines.append(
                f'http_request_duration_seconds_sum{{service="{self.service}",method="{method}",path="{path}"}} {total:.6f}'
            )
            lines.append(
                f'http_request_duration_seconds_count{{service="{self.service}",method="{method}",path="{path}"}} {count}'
            )

        lines.append("# HELP http_server_errors_total Total 5xx errors")
        lines.append("# TYPE http_server_errors_total counter")
        for key, count in sorted(self._server_errors.items()):
            method, path, tq = key.split("|", 2)
            lines.append(
                f'http_server_errors_total{{service="{self.service}",method="{method}",path="{path}",tenant_query="{tq}"}} {count}'
            )

        lines.append("# HELP http_client_errors_total Total 4xx errors")
        lines.append("# TYPE http_client_errors_total counter")
        for key, count in sorted(self._client_errors.items()):
            method, path, tq = key.split("|", 2)
            lines.append(
                f'http_client_errors_total{{service="{self.service}",method="{method}",path="{path}",tenant_query="{tq}"}} {count}'
            )

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

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        hdr_tid = (request.headers.get("x-trace-id") or "").strip()
        trace_id = hdr_tid if hdr_tid else uuid.uuid4().hex[:16]

        rule_set_hash = (
            request.headers.get("x-rule-set-hash")
            or request.headers.get("X-Rule-Set-Hash")
            or ""
        ).strip()

        tenant_query = (request.query_params.get("tenant_id") or "").strip()
        tenant_hdr = (
            request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-Id") or ""
        ).strip()
        tenant_id = tenant_query or tenant_hdr

        otel_trace_id = _parse_w3c_trace_id_from_traceparent(
            request.headers.get("traceparent")
        )
        if not otel_trace_id:
            raw_otel = (
                request.headers.get("x-otel-trace-id")
                or request.headers.get("X-Otel-Trace-Id")
                or ""
            ).strip()
            if len(raw_otel) == 32 and all(
                c in "0123456789abcdefABCDEF" for c in raw_otel
            ):
                otel_trace_id = raw_otel.lower()
        if not otel_trace_id and len(hdr_tid) == 32 and all(
            c in "0123456789abcdefABCDEF" for c in hdr_tid
        ):
            otel_trace_id = hdr_tid.lower()

        clear_contextvars()
        bind_contextvars(
            trace_id=trace_id,
            rule_set_hash=rule_set_hash,
            tenant_id=tenant_id,
            otel_trace_id=otel_trace_id,
        )
        sync_rule_engine_tracing_bridge()
        _bind_sentry_http_scope(trace_id, otel_trace_id)

        request.state.trace_id = trace_id
        request.state.rule_set_hash = rule_set_hash
        request.state.tenant_id = tenant_id
        request.state.otel_trace_id = otel_trace_id

        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except BaseException:
            clear_contextvars()
            raise

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

        tq = "present" if (request.query_params.get("tenant_id") or "").strip() else "absent"
        self._metrics.record_request(
            request.method,
            path,
            response.status_code,
            duration,
            tenant_query_scope=tq,
        )
        response.headers["X-Trace-Id"] = trace_id

        log = structlog.get_logger(f"{self._service}.http")
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        clear_contextvars()
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
