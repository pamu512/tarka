"""Single process: event ingest (NATS + Decision API fan-out) + analytics (ClickHouse query + sink)."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Sub-apps skip their own Prometheus/middleware when this is set (see event_ingest / analytics_sink).
os.environ["TARKA_DATA_PLANE_SUBAPP"] = "1"

from fastapi import Depends, FastAPI, Request

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


@asynccontextmanager
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

    skip = {"/v1/health", "/metrics"}
    _merge_routes(app, ei.app, skip_paths=skip)
    _merge_routes(app, asink.app, skip_paths=skip)

    @app.get("/v1/health")
    async def combined_health(request: Request) -> dict:
        r = getattr(request.app.state, "redis", None)
        redis_configured = r is not None
        redis_ok: bool | None = None
        if r is not None:
            try:
                await r.ping()
                redis_ok = True
            except Exception:
                redis_ok = False
        ingest_body = {
            "nats_connected": ei._nc is not None and ei._nc.is_connected,
            "redis_configured": redis_configured,
            "redis_ok": redis_ok,
        }
        return {
            "status": "ok",
            "ingest": ingest_body,
            "analytics": {"clickhouse": asink._ch_client is not None},
        }

    @app.get("/v1/ready")
    async def ready(request: Request) -> dict:
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
        nats_ok = ei._nc is not None and getattr(ei._nc, "is_connected", False)
        checks = {
            "nats_connected": nats_ok,
            "http_client": http_ok,
            "redis_ok": True if r is None else (redis_ok is True),
        }
        ready_flag = bool(nats_ok and http_ok and checks["redis_ok"])
        return {"ready": ready_flag, "checks": checks}

    @app.get("/v1/schema-registry/status", dependencies=[Depends(ei.require_api_key)])
    async def schema_registry_status() -> dict:
        return {"schema_id": "fraud-event", "versions": ["1.0.0"]}

    return app


app = create_app()
