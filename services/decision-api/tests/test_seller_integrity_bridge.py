"""Evaluate → seller integrity bridge (Marketplace B3)."""

from __future__ import annotations

import httpx
import pytest

from decision_api.decision_outcome import DecisionOutcomeContext, schedule_decision_outcomes
from decision_api.seller_integrity_bridge import (
    build_seller_payload,
    maybe_record_seller_integrity,
    should_record_seller_integrity,
)


def test_should_record_on_delivery_checkpoint():
    assert should_record_seller_integrity(
        metadata={"checkpoint": "delivery", "seller_id": "s1"},
    )
    assert should_record_seller_integrity(
        metadata={"seller_id": "s1"},
        event_type="checkout",
    )


def test_should_record_when_seller_id_and_counts():
    assert should_record_seller_integrity(
        metadata={
            "seller_id": "s1",
            "successful_deliveries": 100,
            "review_count": 30,
        },
    )
    assert should_record_seller_integrity(
        metadata={"seller_id": "s1", "review_count": 5},
    )


def test_should_not_record_without_seller_id():
    assert not should_record_seller_integrity(
        metadata={"checkpoint": "delivery"},
    )
    assert not should_record_seller_integrity(
        metadata={"checkpoint": "order", "successful_deliveries": 10},
    )


def test_build_seller_payload_maps_fields():
    body = build_seller_payload(
        tenant_id="ten",
        metadata={"checkpoint": "delivery"},
        payload={
            "seller_id": "seller-abc",
            "successful_deliveries": 200,
            "review_count": 70,
            "window_days": 14,
        },
    )
    assert body["tenant_id"] == "ten"
    assert body["seller_id"] == "seller-abc"
    assert body["successful_deliveries"] == 200
    assert body["review_count"] == 70
    assert body["window_days"] == 14


@pytest.mark.asyncio
async def test_maybe_record_seller_integrity_posts_to_ingress():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["token"] = request.headers.get("X-Internal-Token")
        import json as _json

        captured["body"] = _json.loads(request.content.decode())
        return httpx.Response(201, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ingress") as client:
        await maybe_record_seller_integrity(
            http=client,
            base_url="http://ingress",
            token="secret-token",
            payload={
                "tenant_id": "demo",
                "seller_id": "s1",
                "successful_deliveries": 50,
                "review_count": 10,
                "window_days": 30,
            },
        )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://ingress/v1/internal/marketplace/seller-integrity"
    assert captured["token"] == "secret-token"
    assert captured["body"]["seller_id"] == "s1"


@pytest.mark.asyncio
async def test_bridge_failure_increments_metric():
    calls = []

    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    await maybe_record_seller_integrity(
        http=Boom(),
        base_url="http://x",
        token="t",
        payload={
            "seller_id": "s1",
            "successful_deliveries": 1,
            "review_count": 0,
        },
        metrics_inc=lambda m, **kw: calls.append(m),
    )
    assert "seller_integrity_bridge_failed" in calls


@pytest.mark.asyncio
async def test_maybe_record_skips_without_config():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await maybe_record_seller_integrity(
            http=client,
            base_url="",
            token="",
            payload={"seller_id": "s1", "successful_deliveries": 0, "review_count": 0},
        )
    assert called is False


def test_schedule_decision_outcomes_enqueues_seller_bridge():
    class _Bg:
        def __init__(self) -> None:
            self.tasks: list[tuple] = []

        def add_task(self, fn, *args, **kwargs):
            self.tasks.append((fn, args, kwargs))

    bg = _Bg()

    async def _noop(*_a, **_k):
        return None

    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="tr-seller",
            tenant_id="ten",
            entity_id="buyer-1",
            event_type="delivery",
            decision="allow",
            score=10.0,
            tags=[],
            metadata={
                "checkpoint": "delivery",
                "seller_id": "seller-99",
                "successful_deliveries": 120,
                "review_count": 40,
            },
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda *_a, **_k: None,
        integration_ingress_url="http://ingress",
        ingress_internal_token="tok",
    )
    bridge_tasks = [
        t
        for t in bg.tasks
        if getattr(t[0], "__name__", "") == "maybe_record_seller_integrity_from_evaluate"
    ]
    assert len(bridge_tasks) == 1
    _fn, _args, kwargs = bridge_tasks[0]
    assert kwargs["tenant_id"] == "ten"
    assert kwargs["metadata"]["seller_id"] == "seller-99"
