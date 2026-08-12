"""Evaluate → payout hold bridge (Marketplace P0 Task 4)."""

from __future__ import annotations

import httpx
import pytest

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    schedule_decision_outcomes,
)
from decision_api.payout_hold_bridge import (
    build_hold_payload,
    maybe_create_payout_hold,
    should_create_payout_hold,
)


def test_should_create_on_event_type_payout():
    assert should_create_payout_hold(
        metadata={"payout_id": "po_1"},
        tags=["action:payout_hold"],
        event_type="payout",
    )
    assert not should_create_payout_hold(
        metadata={"checkpoint": "order"},
        tags=["action:payout_hold"],
        event_type="purchase",
    )


def test_resolve_delay_pending_and_hold_wins():
    from decision_api.payout_hold_bridge import resolve_hold_status_and_hours

    assert resolve_hold_status_and_hours(["action:payout_delay"]) == ("pending", 24)
    assert resolve_hold_status_and_hours(
        ["action:payout_hold", "action:payout_delay"]
    ) == ("held", 72)


def test_build_hold_payload_pending_for_delay():
    p = build_hold_payload(
        tenant_id="t",
        entity_id="e",
        tags=["action:payout_delay"],
        metadata={"checkpoint": "payout", "payout_id": "po_1"},
        decision_id="d",
        trace_id="tr",
    )
    assert p["status"] == "pending"
    assert p["hold_duration_hours"] == 24


def test_should_create_on_payout_checkpoint_and_action_tag():
    assert should_create_payout_hold(
        metadata={"checkpoint": "payout", "payout_id": "po_9"},
        tags=["vertical:marketplace", "action:payout_hold"],
    )
    assert not should_create_payout_hold(
        metadata={"checkpoint": "order"}, tags=["action:payout_hold"]
    )
    assert not should_create_payout_hold(
        metadata={"checkpoint": "payout"}, tags=["risk:promo_farm"]
    )


def test_should_create_on_dispatch_with_courier_spoof():
    assert should_create_payout_hold(
        metadata={"checkpoint": "dispatch", "courier_payout_id": "cp_1"},
        tags=["vertical:qcommerce", "risk:courier_spoof"],
    )
    assert should_create_payout_hold(
        metadata={"checkpoint": "deliver", "transfer_id": "tx_1"},
        tags=["vendor:incognia:high_risk"],
    )


def test_should_not_create_on_dispatch_without_spoof_tags():
    assert not should_create_payout_hold(
        metadata={"checkpoint": "dispatch", "payout_id": "po_1"},
        tags=["vertical:logistics", "action:payout_delay"],
    )
    assert not should_create_payout_hold(
        metadata={"checkpoint": "dispatch", "payout_id": "po_1"},
        tags=["risk:promo_farm"],
    )


def test_build_hold_payload_maps_fields():
    p = build_hold_payload(
        tenant_id="t",
        entity_id="e",
        tags=["action:payout_delay"],
        metadata={"checkpoint": "payout", "payout_id": "po_1", "amount": 50},
        decision_id="d",
        trace_id="tr",
    )
    assert p["payout_id"] == "po_1"
    assert p["status"] == "pending"
    assert p["hold_duration_hours"] == 24
    assert "action:payout_delay" in p["tags"]
    assert p["amount"] == 50.0
    assert p["hold_reason"] == "tag:action:payout_delay"


@pytest.mark.asyncio
async def test_maybe_create_payout_hold_posts_to_ingress():
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
        await maybe_create_payout_hold(
            http=client,
            base_url="http://ingress",
            token="secret-token",
            payload={
                "tenant_id": "demo",
                "payout_id": "po_1",
                "entity_id": "e1",
                "status": "held",
            },
        )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://ingress/v1/internal/marketplace/payout-holds"
    assert captured["token"] == "secret-token"
    assert captured["body"]["payout_id"] == "po_1"


@pytest.mark.asyncio
async def test_bridge_failure_increments_metric():
    calls = []

    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    await maybe_create_payout_hold(
        http=Boom(),
        base_url="http://x",
        token="t",
        payload={
            "tenant_id": "t",
            "payout_id": "p",
            "entity_id": "e",
            "status": "held",
        },
        metrics_inc=lambda m, **kw: calls.append(m),
    )
    assert "payout_hold_bridge_failed" in calls


@pytest.mark.asyncio
async def test_maybe_create_payout_hold_skips_without_config():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await maybe_create_payout_hold(
            http=client,
            base_url="",
            token="",
            payload={"payout_id": "po_1"},
        )
    assert called is False


def test_schedule_decision_outcomes_enqueues_payout_hold_bridge():
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
            trace_id="tr-1",
            tenant_id="ten",
            entity_id="e1",
            event_type="payout",
            decision="review",
            score=70.0,
            tags=["action:payout_hold", "vertical:marketplace"],
            metadata={"checkpoint": "payout", "payout_id": "po_99", "amount": 10},
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
        if getattr(t[0], "__name__", "") == "maybe_create_payout_hold_from_evaluate"
    ]
    assert len(bridge_tasks) == 1
    _fn, args, kwargs = bridge_tasks[0]
    assert kwargs["tenant_id"] == "ten"
    assert kwargs["metadata"]["payout_id"] == "po_99"


def test_schedule_skips_bridge_when_not_payout_checkpoint():
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
            trace_id="tr-2",
            tenant_id="ten",
            entity_id="e1",
            event_type="order",
            decision="allow",
            score=10.0,
            tags=["action:payout_hold"],
            metadata={"checkpoint": "order", "payout_id": "po_x"},
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
        if getattr(t[0], "__name__", "") == "maybe_create_payout_hold_from_evaluate"
    ]
    assert bridge_tasks == []
