"""ASGI application for the Tarka management service."""

from __future__ import annotations

from fastapi import FastAPI

from tarka_management.api import router as signal_lineage_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tarka Management",
        version="0.2.0",
        description="Management-plane APIs (immutable registry clients, YAML signal lineage).",
    )
    app.include_router(signal_lineage_router)
    return app


app = create_app()
