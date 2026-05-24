"""Gate: orchestrator JetStream shadow.investigate pull consumer ack/nak semantics."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_SHADOW = Path(__file__).resolve().parents[2] / "shadow_agent" / "src"
for _p in (_SRC_ORCH, _SRC_SHADOW):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_process_message_acks_after_successful_commit() -> None:
    async def _run() -> None:
        from orchestrator.workers.nats_shadow_investigate import process_shadow_investigate_message

        msg = MagicMock()
        msg.data = b'{"session_id":"s1","entity_id":"e1","transaction":{"entity_id":"e1"}}'
        msg.ack = AsyncMock()
        msg.nak = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "shadow_agent.workers.shadow_investigate_handler.handle_shadow_investigate_payload",
                AsyncMock(return_value=True),
            )
            await process_shadow_investigate_message(MagicMock(), msg)

        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()

    asyncio.run(_run())


def test_process_message_acks_unrecoverable_skip_without_transaction() -> None:
    async def _run() -> None:
        from orchestrator.workers.nats_shadow_investigate import process_shadow_investigate_message

        msg = MagicMock()
        msg.data = b'{"session_id":"legacy"}'
        msg.ack = AsyncMock()
        msg.nak = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "shadow_agent.workers.shadow_investigate_handler.handle_shadow_investigate_payload",
                AsyncMock(return_value=False),
            )
            await process_shadow_investigate_message(MagicMock(), msg)

        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()

    asyncio.run(_run())


def test_process_message_naks_retryable_engine_failure() -> None:
    async def _run() -> None:
        from tarka_shared.audit_errors import AuditPersistenceError

        from orchestrator.workers.nats_shadow_investigate import process_shadow_investigate_message

        msg = MagicMock()
        msg.data = b'{"session_id":"s1","entity_id":"e1","transaction":{"entity_id":"e1"}}'
        msg.ack = AsyncMock()
        msg.nak = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "shadow_agent.workers.shadow_investigate_handler.handle_shadow_investigate_payload",
                AsyncMock(
                    side_effect=AuditPersistenceError.persist_failed(entity_id="e1", component="shadow"),
                ),
            )
            await process_shadow_investigate_message(MagicMock(), msg)

        msg.nak.assert_awaited_once_with(delay=5)
        msg.ack.assert_not_awaited()

    asyncio.run(_run())


def test_run_pull_consumer_uses_fetch_batch_ten() -> None:
    async def _run() -> None:
        from orchestrator.workers import nats_shadow_investigate as mod

        stop = asyncio.Event()

        msg = MagicMock()
        msg.data = b"{}"
        msg.ack = AsyncMock()

        async def _fetch(**kwargs: object) -> list[MagicMock]:
            stop.set()
            return [msg]

        sub = MagicMock()
        sub.fetch = AsyncMock(side_effect=_fetch)

        js = MagicMock()
        js.pull_subscribe = AsyncMock(return_value=sub)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(mod, "ensure_shadow_investigate_stream", AsyncMock())
            mp.setattr(mod, "process_shadow_investigate_message", AsyncMock())
            mp.setattr(mod, "shadow_investigate_fetch_batch_size", lambda: 10)
            await mod.run_pull_consumer(runtime=MagicMock(), js=js, subject="shadow.investigate", stop=stop)

        sub.fetch.assert_awaited()
        assert sub.fetch.await_args.kwargs["batch"] == 10

    asyncio.run(_run())
