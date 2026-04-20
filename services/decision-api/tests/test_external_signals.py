from __future__ import annotations

import httpx
import pytest
from decision_api.config import settings
from decision_api.external_signals import evaluate_external_signals
from decision_api.schemas import EvaluateRequest


def _body() -> EvaluateRequest:
    return EvaluateRequest(
        tenant_id="demo",
        entity_id="acct_1",
        event_type="payment",
        payload={"phone": "+85212345678"},
    )


async def _mock_http(payload: dict) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_evaluate_external_signals_returns_none_when_no_provider(monkeypatch):
    monkeypatch.setattr(settings, "scameter_enabled", False)
    monkeypatch.setattr(settings, "scameter_base_url", "")
    http = await _mock_http({})
    try:
        out = await evaluate_external_signals(http, _body(), {})
    finally:
        await http.aclose()
    assert out is None


@pytest.mark.asyncio
async def test_evaluate_external_signals_maps_scameter_response(monkeypatch):
    monkeypatch.setattr(settings, "scameter_enabled", True)
    monkeypatch.setattr(settings, "scameter_base_url", "http://scameter.local")
    monkeypatch.setattr(settings, "scameter_api_key", "test")
    monkeypatch.setattr(settings, "external_signal_timeout_seconds", 0.5)
    http = await _mock_http(
        {
            "risk_score": 77.0,
            "confidence": 0.91,
            "signals": ["phone_reputation_bad"],
            "model_version": "v2",
        }
    )
    try:
        out = await evaluate_external_signals(http, _body(), {"ip_address": "1.2.3.4"})
    finally:
        await http.aclose()
    assert out is not None
    assert out["providers"] == ["scameter"]
    assert out["risk_score"] == 77.0
    assert out["score_delta"] > 0
    assert "scameter_high_risk" in out["tags"]
