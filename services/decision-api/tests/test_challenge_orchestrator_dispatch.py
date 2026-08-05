"""Missed-mark bridge B3: challenge webhook dispatches for step-up actions."""

from __future__ import annotations

import httpx
import pytest

from decision_api.challenge_orchestrator import maybe_dispatch_challenge_webhook


@pytest.mark.asyncio
async def test_challenge_webhook_posts_when_configured(monkeypatch):
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_URL", "https://merchant.test/hook")
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_SECRET", "sec")

    captured: dict = {}

    async def _post(url, content=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = content
        return httpx.Response(204)

    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    async with httpx.AsyncClient(transport=transport) as client:
        client.post = _post  # type: ignore[method-assign]
        out = await maybe_dispatch_challenge_webhook(
            http=client,
            trace_id="t1",
            tenant_id="ten",
            entity_id="e1",
            decision="review",
            recommended_action="step_up",
            challenge_metadata={"step_up_url": "https://app/challenge"},
        )
    assert out is not None
    assert out.get("dispatched") is True
    assert captured.get("url") == "https://merchant.test/hook"
    assert captured["headers"].get("x-tarka-signature")


@pytest.mark.asyncio
async def test_challenge_webhook_skips_when_not_step_up(monkeypatch):
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_URL", "https://merchant.test/hook")
    async with httpx.AsyncClient() as client:
        out = await maybe_dispatch_challenge_webhook(
            http=client,
            trace_id="t1",
            tenant_id="ten",
            entity_id="e1",
            decision="allow",
            recommended_action="allow",
        )
    assert out is None
