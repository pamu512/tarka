"""Gate: VelocityUpdateHandler Redis MULTI/EXEC (CH mirror removed)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
for _p in (_SRC_ORCH,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_velocity_update_handler_applies_redis_only() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.velocity_update import VelocityUpdateHandler

        pipe = MagicMock()
        pipe.zadd = MagicMock(return_value=pipe)
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

        await handler.execute(payload)

        zadd_keys = [call.args[0] for call in pipe.zadd.call_args_list]
        assert any(key.endswith(":device:device-hash-token:events") for key in zadd_keys)
        assert any(":ip:192.0.2.1:events" in key for key in zadd_keys)
        assert all(":entity-1:" not in key for key in zadd_keys)
        ch_client.insert.assert_not_called()
        ch_client.command.assert_not_called()

    asyncio.run(_run())


def test_velocity_update_handler_requires_amount_cents() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.velocity_update import (
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


@pytest.mark.asyncio
async def test_velocity_handler_records_device_and_ip_on_aggregate_store() -> None:
    from workers.handlers.velocity_update import VelocityUpdateHandler

    calls: list[tuple] = []

    class _Store:
        async def record_event(self, tenant_id, entity_id, event_id, fields, ts=None):
            calls.append((tenant_id, entity_id, event_id, fields, ts))

    handler = VelocityUpdateHandler(deps=type("D", (), {"redis_client": object()})())
    handler._aggregate_store = _Store()
    await handler.execute(
        {
            "schema": "tarka.velocity_update.v1",
            "entity_id": "evt-1",
            "device_hash_string": "devtok",
            "amount_cents": 500,
            "transaction_timestamp_utc": "2026-11-17T00:00:00Z",
            "client_browser_metadata_context": {
                "tenant_id": "acme",
                "ingress_ip": "203.0.113.9",
            },
        }
    )
    # 2026-11-17T00:00:00Z
    assert ("acme", "device:devtok", "evt-1", {"amount": 500}, 1794873600) in calls
    assert ("acme", "ip:203.0.113.9", "evt-1", {"amount": 500}, 1794873600) in calls
    assert all(call[1] != "evt-1" for call in calls)
