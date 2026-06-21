"""Gate: TARKA_EVENTS JetStream initializer connects and declares limits stream."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_stream_config_uses_limits_retention_and_subjects() -> None:
    from nats.js.api import RetentionPolicy, StorageType

    from messaging.nats_jetstream import (
        TARKA_EVENTS_STREAM_NAME,
        TARKA_EVENTS_SUBJECTS,
        TarkaEventsJetStreamInitializer,
    )

    init = TarkaEventsJetStreamInitializer(
        nats_url="nats://127.0.0.1:4222",
        max_age_sec=3600.0,
        max_bytes=1024,
    )
    cfg = init.stream_config()
    assert cfg.name == TARKA_EVENTS_STREAM_NAME
    assert cfg.subjects == list(TARKA_EVENTS_SUBJECTS)
    assert cfg.retention == RetentionPolicy.LIMITS
    assert cfg.max_age == 3600.0
    assert cfg.max_bytes == 1024
    assert cfg.storage == StorageType.FILE


def test_connect_declares_stream_when_missing() -> None:
    async def _run() -> None:
        from nats.js.errors import NotFoundError

        from messaging.nats_jetstream import TarkaEventsJetStreamInitializer

        js = AsyncMock()
        js.account_info = AsyncMock(return_value=SimpleNamespace())
        js.stream_info = AsyncMock(side_effect=NotFoundError())
        js.add_stream = AsyncMock()
        js.update_stream = AsyncMock()

        nc = MagicMock()
        nc.jetstream = MagicMock(return_value=js)
        nc.drain = AsyncMock()

        with patch("nats.connect", AsyncMock(return_value=nc)) as connect_mock:
            init = TarkaEventsJetStreamInitializer(
                nats_url="nats://127.0.0.1:4222",
                max_age_sec=7200.0,
                max_bytes=2048,
            )
            await init.connect()

        connect_mock.assert_awaited_once_with("nats://127.0.0.1:4222")
        js.account_info.assert_awaited_once()
        js.add_stream.assert_awaited_once()
        cfg = js.add_stream.await_args.args[0]
        assert cfg.max_age == 7200.0
        assert cfg.max_bytes == 2048
        js.update_stream.assert_not_awaited()
        await init.close()
        nc.drain.assert_awaited()

    asyncio.run(_run())


def test_connect_updates_stream_when_present() -> None:
    async def _run() -> None:
        from messaging.nats_jetstream import TarkaEventsJetStreamInitializer

        js = AsyncMock()
        js.account_info = AsyncMock(return_value=SimpleNamespace())
        js.stream_info = AsyncMock(return_value=SimpleNamespace())
        js.add_stream = AsyncMock()
        js.update_stream = AsyncMock()

        nc = MagicMock()
        nc.jetstream = MagicMock(return_value=js)
        nc.drain = AsyncMock()

        with patch("nats.connect", AsyncMock(return_value=nc)):
            init = TarkaEventsJetStreamInitializer(
                nats_url="nats://127.0.0.1:4222",
                max_age_sec=1800.0,
                max_bytes=4096,
            )
            await init.connect()

        js.add_stream.assert_not_awaited()
        js.update_stream.assert_awaited_once()
        cfg = js.update_stream.await_args.args[0]
        assert cfg.max_age == 1800.0
        assert cfg.max_bytes == 4096
        await init.close()

    asyncio.run(_run())


def test_connect_raises_when_jetstream_account_unavailable() -> None:
    async def _run() -> None:
        from messaging.nats_jetstream import (
            JetStreamUnavailableError,
            TarkaEventsJetStreamInitializer,
        )

        js = AsyncMock()
        js.account_info = AsyncMock(side_effect=RuntimeError("jetstream disabled"))

        nc = MagicMock()
        nc.jetstream = MagicMock(return_value=js)
        nc.drain = AsyncMock()

        with patch("nats.connect", AsyncMock(return_value=nc)):
            init = TarkaEventsJetStreamInitializer(
                nats_url="nats://127.0.0.1:4222",
                max_age_sec=60.0,
                max_bytes=512,
            )
            with pytest.raises(JetStreamUnavailableError):
                await init.connect()

        nc.drain.assert_awaited()

    asyncio.run(_run())
