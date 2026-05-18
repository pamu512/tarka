"""HMAC request signing middleware and shared canonical helpers."""

import json

import httpx
import pytest
from decision_api.request_signature_middleware import RequestSignatureMiddleware
from fastapi import FastAPI
from tarka_request_signature import build_signature_headers, verify_signature


def test_tarka_request_signature_roundtrip():
    body = b'{"tenant_id":"t1","event_type":"login","entity_id":"u1","payload":{}}'
    secret = "unit-test-secret"
    hdrs = build_signature_headers(body, secret=secret)
    assert verify_signature(body, hdrs, secret=secret)
    assert not verify_signature(body + b"x", hdrs, secret=secret)


@pytest.fixture
async def signed_echo_app():
    app = FastAPI()

    @app.post("/v1/decisions/evaluate")
    async def _echo():
        return {"ok": True}

    app.add_middleware(RequestSignatureMiddleware, secret="mw-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_middleware_rejects_unsigned_post(signed_echo_app):
    r = await signed_echo_app.post(
        "/v1/decisions/evaluate",
        content=json.dumps(
            {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_middleware_accepts_signed_post(signed_echo_app):
    raw = json.dumps(
        {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}}
    ).encode()
    hdrs = build_signature_headers(raw, secret="mw-secret")
    r = await signed_echo_app.post(
        "/v1/decisions/evaluate",
        content=raw,
        headers={"Content-Type": "application/json", **hdrs},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
