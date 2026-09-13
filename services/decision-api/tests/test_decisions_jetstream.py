"""A4: decision-api must ensure its FRAUD_DECISIONS stream exists (cold-start race).

Only analytics-sink created the stream today. If decision-api starts first (or
analytics-sink is absent), every ``fraud.decisions.*`` JetStream publish fails
with NoStreamResponseError and decisions are silently dropped (logged warning).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_ensure_adds_stream_when_missing() -> None:
    from decision_api.decisions_jetstream import ensure_decisions_stream

    find = AsyncMock(side_effect=Exception("no stream"))
    add = AsyncMock()
    js = SimpleNamespace(find_stream_name_by_subject=find, add_stream=add)

    await ensure_decisions_stream(js)

    find.assert_awaited_once_with("fraud.decisions.>")
    add.assert_awaited_once()
    kwargs = add.await_args.kwargs
    assert kwargs["name"] == "FRAUD_DECISIONS"
    assert kwargs["subjects"] == ["fraud.decisions.>"]
    assert kwargs["retention"] == "limits"


@pytest.mark.asyncio
async def test_ensure_noop_when_stream_present() -> None:
    from decision_api.decisions_jetstream import ensure_decisions_stream

    find = AsyncMock(return_value="FRAUD_DECISIONS")
    add = AsyncMock()
    js = SimpleNamespace(find_stream_name_by_subject=find, add_stream=add)

    await ensure_decisions_stream(js)

    find.assert_awaited_once_with("fraud.decisions.>")
    add.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_never_raises_on_broken_jetstream() -> None:
    """Startup must survive a NATS without JetStream enabled (logged, not fatal)."""
    from decision_api.decisions_jetstream import ensure_decisions_stream

    js = SimpleNamespace(
        find_stream_name_by_subject=AsyncMock(side_effect=Exception("js unavailable")),
        add_stream=AsyncMock(side_effect=Exception("still unavailable")),
    )

    await ensure_decisions_stream(js)  # must not raise
