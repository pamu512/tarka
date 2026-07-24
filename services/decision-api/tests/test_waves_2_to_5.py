from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.challenge_orchestrator import maybe_dispatch_challenge_webhook
from decision_api.inference_build import build_inference_context
from decision_api.integrity_policy import (
    integrity_policy_matrix,
    platform_meets_high_confidence,
)


def test_integrity_policy_matrix_shape():
    m = integrity_policy_matrix()
    assert m["schema_id"] == "tarka.integrity_policy_matrix/v1"
    assert "android" in m["platforms"]
    assert m["platforms"]["android"]["attestation_provider"] == "play_integrity"


def test_platform_high_confidence():
    assert not platform_meets_high_confidence("android", integrity_confidence=0.4)
    assert platform_meets_high_confidence(
        "android",
        integrity_confidence=0.8,
        verified_signals=["play_integrity_verified"],
    )


def test_graph_peer_boosts_copresence():
    ctx = build_inference_context(
        [],
        [],
        None,
        20.0,
        {"graph_seen_at_peer_count_24h": 4},
        graph_meta={"seen_at_peer_count_24h": 4},
    )
    assert ctx["copresence_risk"] >= 0.4


@pytest.mark.asyncio
async def test_challenge_webhook_dispatch(monkeypatch):
    seen: dict = {}

    class FakeResp:
        status_code = 204

    class FakeHttp:
        async def post(self, url, content=None, headers=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            seen["body"] = content
            return FakeResp()

    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_URL", "https://hooks.example/challenge")
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_SECRET", "sekret")
    out = await maybe_dispatch_challenge_webhook(
        http=FakeHttp(),  # type: ignore[arg-type]
        trace_id="t1",
        tenant_id="acme",
        entity_id="u1",
        decision="review",
        recommended_action="step_up_mfa",
        challenge_metadata={"policy_id": "default_v1"},
    )
    assert out and out["ok"] is True
    assert seen["url"].endswith("/challenge")
    sig = seen["headers"]["x-tarka-signature"]
    expect = hmac.new(b"sekret", seen["body"], hashlib.sha256).hexdigest()
    assert sig == expect


@pytest.mark.asyncio
async def test_simulation_rejects_underpowered(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from decision_api.simulation_api import router

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/simulation/run",
            json={
                "scenario": "custom",
                "custom_profile": {
                    "name": "tiny",
                    "total_events": 50,
                    "fraud_rate": 0.1,
                },
                "allow_underpowered": False,
            },
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["reason_code"] == "SIMULATION_UNDERPOWERED"
