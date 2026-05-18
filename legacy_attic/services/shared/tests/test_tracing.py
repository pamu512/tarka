from __future__ import annotations

import site
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

site.addsitedir(str(Path(__file__).resolve().parents[1]))
from tarka_shared.tracing import setup_tracing


def test_setup_tracing_adds_traceparent_header_when_missing():
    app = FastAPI()
    setup_tracing(app, "test-service")

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.headers.get("traceparent", "").startswith("00-")


def test_setup_tracing_preserves_incoming_traceparent():
    app = FastAPI()
    setup_tracing(app, "test-service")

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    incoming = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    with TestClient(app) as client:
        resp = client.get("/ping", headers={"traceparent": incoming})
    assert resp.status_code == 200
    assert resp.headers.get("traceparent") == incoming
