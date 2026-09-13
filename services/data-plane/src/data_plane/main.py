"""Single process: event ingest (NATS + Decision API fan-out) + analytics (ClickHouse query + sink)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Sub-apps skip their own Prometheus/middleware when this is set (see event_ingest / analytics_sink).
os.environ["TARKA_DATA_PLANE_SUBAPP"] = "1"

from fastapi import Depends, FastAPI, Request
from starlette.responses import JSONResponse

# Shared observability (PYTHONPATH includes services/shared in Docker / CI).
for parent in Path(__file__).resolve().parents:
    candidate = parent / "shared"
    if candidate.is_dir() and (candidate / "observability.py").is_file():
        sys.path.insert(0, str(candidate))
        break
else:
    _fallback = Path(__file__).resolve().parents[3] / "shared"
    sys.path.insert(0, str(_fallback))

import analytics_sink.main as asink  # noqa: E402
import event_ingest.main as ei  # noqa: E402
from observability import setup_observability  # noqa: E402

log = logging.getLogger("data-plane")

# event-ingest /v1/ready is NATS-only. Combined health/ready own those paths.
SUBAPP_SKIP_PATHS = {"/v1/health", "/v1/ready", "/metrics"}


def ready_http(
    *,
    nats_ok: bool,
    http_ok: bool,
    redis_ok: bool,
    clickhouse_ok: bool | None = None,
) -> tuple[int, dict[str, Any]]:
    ready_flag = bool(nats_ok and http_ok and redis_ok)
    checks: dict[str, Any] = {
        "nats_connected": nats_ok,
        "http_client": http_ok,
        "redis_ok": redis_ok,
    }
    if clickhouse_ok is not None:
        checks["clickhouse_ok"] = clickhouse_ok
        ready_flag = ready_flag and bool(clickhouse_ok)
    body = {"ready": ready_flag, "checks": checks}
    return (200, body) if ready_flag else (503, body)


def _doc_path(path: str | None) -> bool:
    if not path:
        return False
    return (
        path in ("/docs", "/redoc", "/openapi.json")
        or path.startswith("/docs/")
        or path.startswith("/redoc/")
    )


def _merge_routes(target: FastAPI, source: FastAPI, *, skip_paths: set[str]) -> None:
    for route in source.routes:
        p = getattr(route, "path", None)
        if _doc_path(p):
            continue
        if p in skip_paths:
            continue
        target.router.routes.append(route)


async def lifespan(app: FastAPI):
    async with ei.lifespan(app), asink.lifespan(app):
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tarka Data Plane",
        version="1.0.0",
        lifespan=lifespan,
    )
    setup_observability(app, "data-plane")

    _merge_routes(app, ei.app, skip_paths=SUBAPP_SKIP_PATHS)
    _merge_routes(app, asink.app, skip_paths=SUBAPP_SKIP_PATHS)

    @app.get("/v1/health")
    async def combined_health(request: Request):
        r = getattr(request.app.state, "redis", None)
        redis_configured = r is not None
        redis_ok: bool | None = None
        if r is not None:
            try:
                await r.ping()
                redis_ok = True
            except Exception:
                redis_ok = False
        nats_ok = ei.nats_connected()
        code, status = ei.liveness_http(
            nats_ok=nats_ok, redis_configured=redis_configured, redis_ok=redis_ok
        )
        ch_configured = asink.clickhouse_configured()
        ch_ok = asink.clickhouse_ok()
        body = {
            "status": status,
            "ingest": {
                "nats_connected": nats_ok,
                "redis_configured": redis_configured,
                "redis_ok": redis_ok,
            },
            "analytics": {"clickhouse": ch_ok, "configured": ch_configured},
        }
        if code != 200:
            return JSONResponse(status_code=code, content=body)
        if ch_configured and not ch_ok:
            body["status"] = "unavailable"
            return JSONResponse(status_code=503, content=body)
        return body

    @app.get("/v1/ready")
    async def ready(request: Request):
        r = getattr(request.app.state, "redis", None)
        redis_ok: bool | None = None
        if r is not None:
            try:
                await r.ping()
                redis_ok = True
            except Exception:
                redis_ok = False
        http = getattr(request.app.state, "http", None)
        http_ok = http is not None
        nats_ok = ei.nats_connected()
        redis_pass = True if r is None else (redis_ok is True)
        ch_ready = asink.clickhouse_ok() if asink.clickhouse_configured() else None
        code, body = ready_http(
            nats_ok=nats_ok, http_ok=http_ok, redis_ok=redis_pass, clickhouse_ok=ch_ready
        )
        if code != 200:
            return JSONResponse(status_code=code, content=body)
        return body

    @app.get("/v1/schema-registry/status", dependencies=[Depends(ei.require_api_key)])
    async def schema_registry_status() -> dict:
        return {"schema_id": "fraud-event", "versions": ["1.0.0"]}

    return app


app = create_app()
