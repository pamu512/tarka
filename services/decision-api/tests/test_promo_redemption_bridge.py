"""Evaluate → promo redemption bridge (Marketplace B3)."""

from __future__ import annotations

import httpx
import pytest

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    schedule_decision_outcomes,
)
from decision_api.promo_redemption_bridge import (
    build_promo_payload,
    maybe_record_promo_redemption,
    should_record_promo_redemption,
)


def test_should_record_on_redeem_checkpoint_with_coupon():
    assert should_record_promo_redemption(
        metadata={"checkpoint": "redeem", "coupon_code": "SAVE10"},
        tags=[],
    )
    assert should_record_promo_redemption(
        metadata={"checkpoint": "promo", "promo_code": "NEW50"},
        tags=[],
    )
    assert should_record_promo_redemption(
        metadata={"coupon_code": "X"},
        tags=[],
        event_type="redeem",
    )


def test_should_record_on_promo_farm_tag():
    assert should_record_promo_redemption(
        metadata={"coupon_code": "FARM"},
        tags=["risk:promo_farm", "vertical:marketplace"],
    )
    assert not should_record_promo_redemption(
        metadata={"coupon_code": "FARM"},
        tags=["risk:collusion_shared_device"],
    )


def test_should_not_record_without_coupon():
    assert not should_record_promo_redemption(
        metadata={"checkpoint": "redeem"},
        tags=["risk:promo_farm"],
    )
    assert not should_record_promo_redemption(
        metadata={"checkpoint": "order", "coupon_code": "X"},
        tags=[],
    )


def test_build_promo_payload_maps_metadata_and_payload():
    body = build_promo_payload(
        tenant_id="ten",
        entity_id="user-1",
        tags=["risk:promo_farm"],
        metadata={"checkpoint": "redeem"},
        payload={"coupon_code": "SAVE20", "order_total": 99.5, "device_id": "dev-1"},
        trace_id="tr-abc",
    )
    assert body["tenant_id"] == "ten"
    assert body["coupon_code"] == "SAVE20"
    assert body["user_id"] == "user-1"
    assert body["device_id"] == "dev-1"
    assert body["order_total"] == 99.5
    assert body["trace_id"] == "tr-abc"
    assert body["flags"] == ["risk:promo_farm"]


@pytest.mark.asyncio
async def test_maybe_record_promo_redemption_posts_to_ingress():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["token"] = request.headers.get("X-Internal-Token")
        import json as _json

        captured["body"] = _json.loads(request.content.decode())
        return httpx.Response(201, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://ingress"
    ) as client:
        await maybe_record_promo_redemption(
            http=client,
            base_url="http://ingress",
            token="secret-token",
            payload={
                "tenant_id": "demo",
                "coupon_code": "SAVE20",
                "user_id": "u1",
                "trace_id": "tr",
            },
        )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://ingress/v1/internal/marketplace/promo-redemptions"
    assert captured["token"] == "secret-token"
    assert captured["body"]["coupon_code"] == "SAVE20"


@pytest.mark.asyncio
async def test_bridge_failure_increments_metric():
    calls = []

    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    await maybe_record_promo_redemption(
        http=Boom(),
        base_url="http://x",
        token="t",
        payload={"coupon_code": "X", "user_id": "u"},
        metrics_inc=lambda m, **kw: calls.append(m),
    )
    assert "promo_redemption_bridge_failed" in calls


@pytest.mark.asyncio
async def test_maybe_record_skips_without_config():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await maybe_record_promo_redemption(
            http=client,
            base_url="",
            token="",
            payload={"coupon_code": "X"},
        )
    assert called is False


def test_schedule_decision_outcomes_enqueues_promo_bridge():
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
            trace_id="tr-promo",
            tenant_id="ten",
            entity_id="u1",
            event_type="custom",
            decision="review",
            score=70.0,
            tags=["risk:promo_farm"],
            metadata={"coupon_code": "SAVE10"},
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
        if getattr(t[0], "__name__", "")
        == "maybe_record_promo_redemption_from_evaluate"
    ]
    assert len(bridge_tasks) == 1
    _fn, _args, kwargs = bridge_tasks[0]
    assert kwargs["tenant_id"] == "ten"
    assert kwargs["metadata"]["coupon_code"] == "SAVE10"
