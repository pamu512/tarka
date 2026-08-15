"""Single process: event ingest (NATS + Decision API fan-out) + analytics (ClickHouse query + sink).

Lite Redis+Postgres platform routes live in ``data_plane.platform`` and keep the
documented port **8014** contract via a temporary compatibility listener
(``TARKA_PLATFORM_COMPAT_PORT``, default unset). ``services/data-platform`` is a
thin re-export of the same app for one release.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
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


def _compat_port() -> int | None:
    """Optional second listener for data-platform storage semantics (default off).

    Removal gate: drop when ``services/data-platform`` and compose ``8014`` bindings
    are removed (rg -n 'TARKA_PLATFORM_COMPAT_PORT|8014').
    """
    raw = os.environ.get("TARKA_PLATFORM_COMPAT_PORT", "").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        log.warning("invalid TARKA_PLATFORM_COMPAT_PORT=%r; compat listener disabled", raw)
        return None
    if port <= 0 or port > 65535:
        return None
    return port


async def _serve_platform_compat(port: int) -> None:
    import uvicorn
    from data_plane.platform.app import create_platform_app

    platform_app = create_platform_app(with_observability=True)
    config = uvicorn.Config(
        platform_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    log.info("data_plane_platform_compat_listener port=%s", port)
    await server.serve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    compat_task: asyncio.Task[Any] | None = None
    port = _compat_port()
    if port is not None:
        compat_task = asyncio.create_task(_serve_platform_compat(port))
        app.state.platform_compat_task = compat_task
    try:
        async with ei.lifespan(app), asink.lifespan(app):
            yield
    finally:
        if compat_task is not None:
            compat_task.cancel()
            try:
                await compat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("platform compat listener shutdown failed")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tarka Data Plane",
        version="1.0.0",
        lifespan=lifespan,
    )
    setup_observability(app, "data-plane")

    skip = {"/v1/health", "/metrics"}
    _merge_routes(app, ei.app, skip_paths=skip)
    _merge_routes(app, asink.app, skip_paths=skip)

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
            "platform_compat_port": _compat_port(),
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
