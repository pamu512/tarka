"""Macroservice: decision-api + case-api in one Uvicorn process."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["TARKA_CORE_API_SUBAPP"] = "1"

for parent in Path(__file__).resolve().parents:
    candidate = parent / "shared"
    if candidate.is_dir() and (candidate / "observability.py").is_file():
        sys.path.insert(0, str(candidate))
        break
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from observability import setup_observability  # noqa: E402

import case_api.main as case  # noqa: E402
import decision_api.main as dec  # noqa: E402
from fastapi import FastAPI  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with dec.lifespan(dec.app):
        async with case.lifespan(case.app):
            yield


def create_app() -> FastAPI:
    app = FastAPI(title="Tarka Core API", version="1.0.0", lifespan=lifespan)
    setup_observability(app, "core-api")

    @app.get("/v1/health")
    async def health() -> dict:
        return {"status": "ok", "service": "core-api"}

    app.mount("/decisions", dec.app)
    app.mount("/cases", case.app)
    return app


app = create_app()
