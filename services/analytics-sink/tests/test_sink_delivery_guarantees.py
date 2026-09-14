"""B1: the analytics sink must never ack data it has not written."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import analytics_sink.main as m


def _msg(payload=b'{"trace_id": "tr1", "score": 1.0}'):
    return SimpleNamespace(
        ack=AsyncMock(), nak=AsyncMock(), data=payload, subject="fraud.events.t1"
    )


def _consumer_env(monkeypatch, *, ch_client, msgs=None, flush=None):
    """Stub the NATS surface so _nats_consumer runs hermetically.

    fetch delivers `msgs` once, then raises CancelledError — the only
    exception shape the consumer loop does not swallow, so every test
    terminates.
    """
    monkeypatch.setattr(m.settings, "clickhouse_host", "ch" if ch_client else "")
    sub = SimpleNamespace(
        fetch=AsyncMock(side_effect=[list(msgs or []), asyncio.CancelledError()])
    )
    nc = SimpleNamespace(close=AsyncMock())
    js = MagicMock()
    js.find_stream_name_by_subject = AsyncMock(return_value="TARKA")
    js.pull_subscribe = AsyncMock(return_value=sub)
    monkeypatch.setattr(m, "_nats_connect", AsyncMock(return_value=(nc, sub)))
    monkeypatch.setattr(m, "_flush_batch", flush or MagicMock(return_value=True))
    monkeypatch.setattr(m, "_FLUSH_RETRY_BACKOFF", 0.01)
    monkeypatch.setattr(m, "_FLUSH_RETRY_SLEEP", 0.01)
    return sub


# ---------- refuse-subscribe (data-deleter guard) ----------


@pytest.mark.asyncio
async def test_consumer_refuses_without_clickhouse(monkeypatch, caplog):
    monkeypatch.setattr(m, "get_metrics", lambda: MagicMock())
    sub = _consumer_env(monkeypatch, ch_client=False)
    with caplog.at_level("WARNING"):
        await m._nats_consumer()
    m._nats_connect.assert_not_awaited()
    assert any("refus" in r.message.lower() for r in caplog.records)
    sub.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_subscribes_when_clickhouse_ready(monkeypatch):
    monkeypatch.setattr(m, "get_metrics", lambda: MagicMock())
    sub = _consumer_env(monkeypatch, ch_client=True)
    sub.fetch = AsyncMock(side_effect=[[], asyncio.CancelledError()])
    with patch.object(m, "_ch_client", MagicMock()), pytest.raises(asyncio.CancelledError):
        await m._nats_consumer()
    m._nats_connect.assert_awaited_once()
    sub.fetch.assert_awaited()


# ---------- ack-after-write ----------


@pytest.mark.asyncio
async def test_ack_only_after_confirmed_flush(monkeypatch):
    flushed = []
    msg = _msg()
    sub = _consumer_env(
        monkeypatch,
        ch_client=True,
        msgs=[msg],
        flush=lambda db, b: flushed.append(list(b)) or True,
    )
    with patch.object(m, "_ch_client", MagicMock()), pytest.raises(asyncio.CancelledError):
        await m._nats_consumer()
    assert flushed and flushed[0], "flush must carry the parsed row"
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_naks_when_flush_fails(monkeypatch):
    msg = _msg()
    sub = _consumer_env(
        monkeypatch,
        ch_client=True,
        msgs=[msg],
        flush=lambda db, b: (_ for _ in ()).throw(RuntimeError("ch down")),
    )
    with patch.object(m, "_ch_client", MagicMock()), pytest.raises(asyncio.CancelledError):
        await m._nats_consumer()
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_failure_returns_false_not_silent(monkeypatch):
    """_flush_batch must report failure, not swallow it (old: log-only + clear)."""
    failing = MagicMock()
    failing.insert.side_effect = RuntimeError("connection refused")
    with patch.object(m, "_ch_client", failing):
        assert m._flush_batch("fraud", [{"trace_id": "tr1", "score": 1.0}]) is False


@pytest.mark.asyncio
async def test_flush_success_returns_true(monkeypatch):
    client = MagicMock()
    with patch.object(m, "_ch_client", client):
        assert m._flush_batch("fraud", [{"trace_id": "tr1", "score": 1.0}]) is True
    client.insert.assert_called_once()


@pytest.mark.asyncio
async def test_no_client_flush_returns_false(monkeypatch):
    """Old test asserted the no-op was fine; B1 flips it: no client = not written."""
    with patch.object(m, "_ch_client", None):
        assert m._flush_batch("fraud", [{"trace_id": "tr1", "score": 1.0}]) is False


def test_every_analytics_route_carries_api_key_dep():
    """B4: app-level deps do not survive the data-plane route merge — the dep
    must live on each route object or :8007 /v1/analytics/* is unauthenticated."""
    from fastapi.routing import APIRoute

    protected = [
        r
        for r in m.app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/v1/analytics")
    ]
    assert protected, "analytics routes missing from app"
    for r in protected:
        calls = [
            getattr(dep, "dependency", None) or getattr(dep, "call", None)
            for dep in r.dependencies
        ]
        assert m.require_api_key in calls, f"{r.path} lacks route-level require_api_key"
