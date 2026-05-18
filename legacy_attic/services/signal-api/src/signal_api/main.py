"""Macroservice: feature + ML + calibration + counter + location (single Uvicorn process)."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["TARKA_SIGNAL_PLANE_SUBAPP"] = "1"

for parent in Path(__file__).resolve().parents:
    candidate = parent / "shared"
    if candidate.is_dir() and (candidate / "observability.py").is_file():
        sys.path.insert(0, str(candidate))
        break
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

import calibration_service.main as cal  # noqa: E402
import counter_service.main as cnt  # noqa: E402
import feature_service.main as feat  # noqa: E402
import location_service.main as loc  # noqa: E402
import ml_scoring.main as ml  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from observability import setup_observability  # noqa: E402

from signal_api.onnx_hot_reload import start_onnx_hot_reload_observer  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with feat.lifespan(feat.app), ml.lifespan(ml.app):
        stop_onnx_watch = start_onnx_hot_reload_observer()
        try:
            yield
        finally:
            stop_onnx_watch()


def create_app() -> FastAPI:
    app = FastAPI(title="Tarka Signal API", version="1.0.0", lifespan=lifespan)
    setup_observability(app, "signal-api")

    @app.get("/v1/health")
    async def health() -> dict:
        return {"status": "ok", "service": "signal-api"}

    app.mount("/features", feat.app)
    app.mount("/ml", ml.app)
    app.mount("/calibration", cal.app)
    app.mount("/counters", cnt.app)
    app.mount("/location", loc.app)
    return app


app = create_app()
