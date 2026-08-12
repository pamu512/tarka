"""Evaluate → loyalty-abuse redeem bridge (Marketplace B2)."""

from __future__ import annotations

import httpx
import pytest

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    schedule_decision_outcomes,
)
from decision_api.loyalty_abuse_bridge import (
    LoyaltyBridgeResult,
    build_loyalty_event,
    friction_to_tags,
    maybe_call_loyalty_abuse,
    maybe_call_loyalty_abuse_from_evaluate,
    reset_loyalty_circuit_for_tests,
    should_call_loyalty_abuse,
)


def test_should_call_on_redeem_checkpoint():
    assert should_call_loyalty_abuse(metadata={"checkpoint": "redeem"})
    assert should_call_loyalty_abuse(metadata={}, event_type="redeem")
    assert not should_call_loyalty_abuse(metadata={"checkpoint": "order"})
    assert not should_call_loyalty_abuse(metadata={}, event_type="payment")


def test_friction_to_tags():
    assert friction_to_tags("allow") == []
    assert friction_to_tags("block") == ["loyalty:friction:block"]
    assert friction_to_tags("soft_challenge") == ["loyalty:friction:soft_challenge"]


def test_build_loyalty_event_maps_fields():
    body = build_loyalty_event(
        tenant_id="ten",
        entity_id="user-1",
        trace_id="tr-abc",
        payload={"points": 50, "ip": "203.0.113.1"},
        metadata={"checkpoint": "redeem", "session_id": "sess-1"},
    )
    ev = body["event"]
    assert ev["type"] == "redeem"
    assert ev["tenant_id"] == "ten"
    assert ev["account_id"] == "user-1"
    assert ev["event_id"] == "tr-abc"
    assert ev["session_id"] == "sess-1"
    assert ev["ip"] == "203.0.113.1"
    assert ev["payload"]["points"] == 50


@pytest.mark.asyncio
async def test_maybe_call_loyalty_abuse_posts_on_redeem():
    reset_loyalty_circuit_for_tests()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        import json as _json

        captured["body"] = _json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"friction": "soft_challenge", "score": 42, "decision_id": "d1"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://loyalty"
    ) as client:
        result = await maybe_call_loyalty_abuse(
            http=client,
            base_url="http://loyalty",
            api_key="la-secret",
            body=build_loyalty_event(
                tenant_id="t",
                entity_id="e",
                trace_id="tr",
                payload={"points": 10},
                metadata={"checkpoint": "redeem"},
            ),
        )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://loyalty/v1/evaluate"
    assert captured["auth"] == "Bearer la-secret"
    assert captured["body"]["event"]["type"] == "redeem"
    assert isinstance(result, LoyaltyBridgeResult)
    assert result.tags == ["loyalty:friction:soft_challenge"]
    assert result.friction == "soft_challenge"
    assert result.score == 42.0
    evidence = result.evidence()
    assert evidence is not None
    assert evidence["source"] == "loyalty_abuse_bridge"
    assert evidence["tags"] == ["loyalty:friction:soft_challenge"]


@pytest.mark.asyncio
async def test_bridge_failure_increments_metric():
    reset_loyalty_circuit_for_tests()
    calls = []

    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    result = await maybe_call_loyalty_abuse(
        http=Boom(),
        base_url="http://x",
        api_key="k",
        body={"event": {"type": "redeem"}},
        metrics_inc=lambda m, **kw: calls.append(m),
        failure_threshold=99,
    )
    assert "enrichment:loyalty_bridge_failed" in result.tags
    assert result.skipped_reason == "call_failed"
    assert "loyalty_abuse_bridge_failed" in calls


@pytest.mark.asyncio
async def test_loyalty_circuit_opens_after_threshold():
    reset_loyalty_circuit_for_tests()
    calls: list[str] = []

    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("down")

    for _ in range(3):
        await maybe_call_loyalty_abuse(
            http=Boom(),
            base_url="http://x",
            api_key="k",
            body={"event": {"type": "redeem"}},
            failure_threshold=3,
            recovery_seconds=60,
        )
    result = await maybe_call_loyalty_abuse(
        http=Boom(),
        base_url="http://x",
        api_key="k",
        body={"event": {"type": "redeem"}},
        metrics_inc=lambda m, **kw: calls.append(m),
        failure_threshold=3,
        recovery_seconds=60,
    )
    assert result.skipped_reason == "circuit_open"
    assert "enrichment:loyalty_circuit_open" in result.tags
    assert "loyalty_abuse_bridge_circuit_open" in calls
    reset_loyalty_circuit_for_tests()


@pytest.mark.asyncio
async def test_maybe_call_skips_when_url_empty():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"friction": "allow"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await maybe_call_loyalty_abuse(
            http=client,
            base_url="",
            api_key="",
            body={"event": {}},
        )
    assert called is False
    assert result.tags == []


def test_schedule_decision_outcomes_does_not_enqueue_loyalty_bridge():
    """Loyalty runs sync in evaluate pipeline so tags reach EvaluateResponse."""

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
            trace_id="tr-redeem",
            tenant_id="ten",
            entity_id="e1",
            event_type="custom",
            decision="allow",
            score=10.0,
            tags=[],
            metadata={"checkpoint": "redeem", "session_id": "s1"},
            payload={"points": 100},
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda *_a, **_k: None,
        loyalty_abuse_url="http://loyalty",
        loyalty_abuse_api_key="tok",
    )
    bridge_tasks = [
        t
        for t in bg.tasks
        if getattr(t[0], "__name__", "") == "maybe_call_loyalty_abuse_from_evaluate"
    ]
    assert bridge_tasks == []


def test_schedule_skips_loyalty_bridge_when_not_redeem():
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
            event_type="payment",
            decision="allow",
            score=10.0,
            tags=[],
            metadata={"checkpoint": "order"},
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda *_a, **_k: None,
        loyalty_abuse_url="http://loyalty",
        loyalty_abuse_api_key="tok",
    )
    bridge_tasks = [
        t
        for t in bg.tasks
        if getattr(t[0], "__name__", "") == "maybe_call_loyalty_abuse_from_evaluate"
    ]
    assert bridge_tasks == []


@pytest.mark.asyncio
async def test_from_evaluate_attaches_incomplete_feed_gate():
    reset_loyalty_circuit_for_tests()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"friction": "allow", "score": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://loyalty"
    ) as client:
        result = await maybe_call_loyalty_abuse_from_evaluate(
            http=client,
            loyalty_abuse_url="http://loyalty",
            loyalty_abuse_api_key="tok",
            tenant_id="t",
            entity_id="e",
            trace_id="tr-feed",
            payload={},
            metadata={
                "checkpoint": "redeem",
                "feed_snapshot": {"orders": [], "refunds": []},
            },
        )
    assert result.feed_gate is not None
    assert result.feed_gate["status"] == "feeds_incomplete"
    assert "loyalty:feeds_incomplete" in result.tags
    ev = result.evidence()
    assert ev is not None
    assert ev["feed_gate"]["claim_allowed"] is False
