"""Refund / offline-cancel bridge contracts against recorded JSON fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from decision_api.offline_cancel_bridge import (
    map_cancel_response,
    maybe_invoke_offline_cancel,
    reset_cancel_circuit_for_tests,
    should_invoke_cancel_bridge,
)
from decision_api.refund_abuse_bridge import (
    map_refund_response,
    maybe_invoke_refund_abuse,
    reset_refund_circuit_for_tests,
    should_invoke_refund_bridge,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "bridges"


def test_refund_recorded_response_maps_hold():
    payload = json.loads(
        (_FIXTURES / "refund_abuse_evaluate_200.json").read_text(encoding="utf-8")
    )
    result = map_refund_response(payload)
    assert result.refund_effect == "hold"
    assert result.abuse_score == 0.88
    assert "action:refund_hold" in result.tags
    assert "risk:refund_burst" in result.tags
    assert "repeat_refund" in result.reason_codes
    ev = result.evidence()
    assert ev is not None and ev["advisory"] is True


def test_maps_heads_from_cancel_recorded_response():
    payload = json.loads(
        (_FIXTURES / "offline_cancel_evaluate_200.json").read_text(encoding="utf-8")
    )
    result = map_cancel_response(payload)
    assert result.heads["cancel_abuse"] == 0.81
    assert "risk:refund_burst" in result.tags
    assert "cancel:head:cancel_abuse" in result.tags


def test_checkpoint_gates():
    assert should_invoke_refund_bridge(metadata={"checkpoint": "refund"})
    assert not should_invoke_refund_bridge(metadata={"checkpoint": "checkout"})
    assert should_invoke_cancel_bridge(metadata={"checkpoint": "cancel"})
    assert not should_invoke_cancel_bridge(metadata={"checkpoint": "checkout"})


@pytest.mark.asyncio
async def test_refund_bridge_posts_recorded_shape(monkeypatch):
    reset_refund_circuit_for_tests()
    recorded = json.loads(
        (_FIXTURES / "refund_abuse_evaluate_200.json").read_text(encoding="utf-8")
    )
    monkeypatch.setenv("TARKA_REFUND_ABUSE_URL", "http://refund.test")
    monkeypatch.setenv("TARKA_REFUND_ABUSE_API_KEY", "rk")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).endswith("/v1/evaluate")
        body = json.loads(request.content.decode())
        assert body["type"] == "refund"
        assert body["tenant_id"] == "t1"
        return httpx.Response(200, json=recorded)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await maybe_invoke_refund_abuse(
            http=client,
            tenant_id="t1",
            entity_id="e1",
            metadata={"checkpoint": "refund"},
            features={"amount": 40},
        )
    assert result.skipped_reason is None
    assert result.abuse_score == 0.88
    assert "action:refund_hold" in result.tags


@pytest.mark.asyncio
async def test_cancel_bridge_posts_recorded_shape(monkeypatch):
    reset_cancel_circuit_for_tests()
    recorded = json.loads(
        (_FIXTURES / "offline_cancel_evaluate_200.json").read_text(encoding="utf-8")
    )
    monkeypatch.setenv("TARKA_OFFLINE_CANCEL_URL", "http://cancel.test")
    monkeypatch.setenv("TARKA_OFFLINE_CANCEL_API_KEY", "ck")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/v1/evaluate")
        return httpx.Response(200, json=recorded)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await maybe_invoke_offline_cancel(
            http=client,
            tenant_id="t1",
            entity_id="e1",
            metadata={"checkpoint": "cancel"},
            features={},
        )
    assert result.skipped_reason is None
    assert result.heads.get("cancel_abuse", 0) >= 0.8


@pytest.mark.asyncio
async def test_refund_bridge_degrades_when_unconfigured(monkeypatch):
    reset_refund_circuit_for_tests()
    monkeypatch.delenv("TARKA_REFUND_ABUSE_URL", raising=False)
    monkeypatch.delenv("REFUND_ABUSE_URL", raising=False)
    result = await maybe_invoke_refund_abuse(
        http=None,
        tenant_id="t",
        entity_id="e",
        metadata={"checkpoint": "refund"},
    )
    assert result.skipped_reason == "bridge_unconfigured"
