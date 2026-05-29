"""Gate: VelocityUpdateHandler Redis MULTI/EXEC + ClickHouse counter mirror."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
for _p in (_SRC_ORCH,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_build_transaction_velocity_incrby_commands_count_and_amount_keys() -> None:
    from orchestrator.anumana_velocity import (
        build_transaction_velocity_incrby_commands,
        device_hash_token,
    )

    fp = "ab" * 32
    dtok = device_hash_token(fp)
    ips = ["192.0.2.1"]
    cmds = build_transaction_velocity_incrby_commands(
        tenant_id="acme",
        device_token=dtok,
        ip_tokens=ips,
        amount_cents=2500,
        now_unix=1_700_000_000,
    )
    assert len(cmds) == 12  # 3 windows * (device cnt+amt + ip cnt+amt)
    count_keys = [c.redis_key for c in cmds if c.increment == 1]
    amt_keys = [c.redis_key for c in cmds if c.increment == 2500]
    assert len(count_keys) == 6
    assert len(amt_keys) == 6
    assert any(k.endswith(":amt") for k in amt_keys)
    assert any(":device:1m:" in k and dtok in k and not k.endswith(":amt") for k in count_keys)
    assert any(":ip:5m:192.0.2.1:" in k for k in count_keys)


def test_apply_velocity_incrby_multi_exec_uses_multi_exec() -> None:
    async def _run() -> None:
        from orchestrator.anumana_velocity import (
            TransactionVelocityCommand,
            apply_velocity_incrby_multi_exec,
        )

        pipe = MagicMock()
        pipe.incrby = MagicMock(return_value=pipe)
        pipe.expire = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[1, True, 2, True])
        redis_client = MagicMock()
        redis_client.pipeline = MagicMock(return_value=pipe)

        cmds = [
            TransactionVelocityCommand("anumana:velocity:t:acme:device:1m:tok:1", 180, 1),
            TransactionVelocityCommand("anumana:velocity:t:acme:device:1m:tok:1:amt", 180, 500),
        ]
        await apply_velocity_incrby_multi_exec(redis_client, cmds)

        redis_client.pipeline.assert_called_once_with(transaction=True)
        pipe.incrby.assert_any_call("anumana:velocity:t:acme:device:1m:tok:1", 1)
        pipe.incrby.assert_any_call("anumana:velocity:t:acme:device:1m:tok:1:amt", 500)
        pipe.expire.assert_any_call("anumana:velocity:t:acme:device:1m:tok:1", 180)
        pipe.expire.assert_any_call("anumana:velocity:t:acme:device:1m:tok:1:amt", 180)
        pipe.execute.assert_awaited_once()

    asyncio.run(_run())


def test_velocity_update_handler_applies_redis_and_clickhouse() -> None:
    async def _run() -> None:
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.velocity_update import VelocityUpdateHandler

        pipe = MagicMock()
        pipe.incrby = MagicMock(return_value=pipe)
        pipe.expire = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[])
        redis_client = MagicMock()
        redis_client.pipeline = MagicMock(return_value=pipe)

        ch_client = MagicMock()
        ch_insert = MagicMock()
        ch_client.command = MagicMock()
        ch_client.insert = ch_insert

        handler = VelocityUpdateHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(),
                graph_client=NullGraphClient(),
                redis_client=redis_client,
                clickhouse_client=ch_client,
            ),
        )
        payload = {
            "schema": "tarka.velocity_update.v1",
            "entity_id": "entity-1",
            "device_hash_string": "device-hash-token",
            "client_browser_metadata_context": {
                "tenant_id": "acme",
                "ingress_ip": "192.0.2.1",
            },
            "amount_cents": 999,
            "transaction_timestamp_utc": "2026-05-09T12:00:00+00:00",
        }

        with patch(
            "orchestrator.workers.handlers.velocity_update.ensure_velocity_counters_table",
        ) as ensure_table:
            await handler.execute(payload)

        redis_client.pipeline.assert_called_once_with(transaction=True)
        pipe.execute.assert_awaited_once()
        ensure_table.assert_called_once_with(ch_client)
        ch_insert.assert_called_once()
        rows = ch_insert.call_args[0][1]
        assert rows
        assert all(len(row) == 2 for row in rows)

    asyncio.run(_run())


def test_velocity_update_handler_requires_amount_cents() -> None:
    async def _run() -> None:
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.velocity_update import (
            VelocityUpdateHandler,
            VelocityUpdatePayloadError,
        )

        handler = VelocityUpdateHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(),
                graph_client=NullGraphClient(),
                redis_client=MagicMock(),
                clickhouse_client=None,
            ),
        )
        with pytest.raises(VelocityUpdatePayloadError, match="amount_cents"):
            await handler.execute(
                {
                    "schema": "tarka.velocity_update.v1",
                    "entity_id": "entity-1",
                    "device_hash_string": "tok",
                    "client_browser_metadata_context": {},
                    "transaction_timestamp_utc": "2026-05-09T12:00:00+00:00",
                },
            )

    asyncio.run(_run())
