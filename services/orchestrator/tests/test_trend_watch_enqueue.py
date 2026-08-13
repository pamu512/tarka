"""Orchestrator trend watch enqueue is best-effort and env-gated."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_maybe_enqueue_trend_watch_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_WATCH_ON_INGEST", "1")
    monkeypatch.setenv("DECISION_API_URL", "http://decision.test")
    monkeypatch.setenv("API_KEYS", "k1")

    from transaction_ingest import maybe_enqueue_trend_watch

    http = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    http.post = AsyncMock(return_value=resp)

    await maybe_enqueue_trend_watch(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        reason="shadow_high_risk",
        decision_api_url="http://decision.test",
    )
    http.post.assert_awaited()
    args, kwargs = http.post.await_args
    assert args[0].endswith("/v1/ops/trend/watch")
    assert kwargs["json"]["entity_id"] == "ent-1"


@pytest.mark.asyncio
async def test_maybe_enqueue_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_WATCH_ON_INGEST", "0")
    monkeypatch.setenv("DECISION_API_URL", "http://decision.test")
    from transaction_ingest import maybe_enqueue_trend_watch

    http = AsyncMock()
    http.post = AsyncMock()
    await maybe_enqueue_trend_watch(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        reason="x",
    )
    http.post.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_enqueue_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_WATCH_ON_INGEST", "1")
    monkeypatch.setenv("DECISION_API_URL", "http://decision.test")
    from transaction_ingest import maybe_enqueue_trend_watch

    http = AsyncMock()
    http.post = AsyncMock(side_effect=RuntimeError("down"))
    await maybe_enqueue_trend_watch(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        reason="x",
    )


@pytest.mark.asyncio
async def test_maybe_enqueue_agent_run_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    monkeypatch.setenv("INVESTIGATION_INTERNAL_SECRET", "s3")
    monkeypatch.setenv("AGENT_RUN_INGEST_TIMEOUT_SEC", "2")
    from transaction_ingest import maybe_enqueue_agent_run

    http = AsyncMock()
    http.post = AsyncMock(return_value=MagicMock())
    await maybe_enqueue_agent_run(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="ingest:tx-1",
        source="shadow",
        context_snapshot={"freshness": {"graph": "present"}},
        claims=[{"text": "hub", "source": "shadow", "evidence_ids": ["graph:1"]}],
    )
    http.post.assert_awaited()
    args, kwargs = http.post.await_args
    assert args[0].endswith("/v1/internal/agent-runs")
    assert kwargs["json"]["source"] == "shadow"
    assert kwargs["headers"]["x-internal-secret"] == "s3"


@pytest.mark.asyncio
async def test_maybe_enqueue_agent_run_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    from transaction_ingest import maybe_enqueue_agent_run

    http = AsyncMock()
    http.post = AsyncMock(side_effect=RuntimeError("down"))
    await maybe_enqueue_agent_run(
        http=http,
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="ingest:tx-1",
        source="shadow",
        context_snapshot={},
    )
