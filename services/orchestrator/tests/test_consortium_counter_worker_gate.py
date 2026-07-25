"""Gate: consortium counter worker + threat-matrix increment helpers."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

_SRC_ORCH = Path(__file__).resolve().parents[1]
for _p in (_SRC_ORCH,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_build_consortium_threat_counter_commands_from_label_event() -> None:
    from orchestrator_analytics.consortium_threat_matrix import (
        build_consortium_threat_counter_commands,
    )
    from messaging.labels_jetstream import NORMALIZED_LABEL_EVENT_SCHEMA

    label_id, cmds = build_consortium_threat_counter_commands(
        {
            "schema": NORMALIZED_LABEL_EVENT_SCHEMA,
            "id": "label-abc",
            "ground_truth_class": "FRAUD",
            "propagated_to_consortium": True,
            "tags": [
                "vector:chargeback",
                "matched_rule:velocity_ip",
                "invalid tag",
            ],
        },
        consortium_id="lane-a",
    )
    assert label_id == "label-abc"
    keys = {c.redis_key for c in cmds}
    assert "anumana:consortium:threat:cid:lane-a:ground_truth:FRAUD" in keys
    assert "anumana:consortium:threat:cid:lane-a:labels_total" in keys
    assert "anumana:consortium:threat:cid:lane-a:tag:vector:chargeback" in keys
    assert "anumana:consortium:threat:cid:lane-a:tag:vector:chargeback:gt:FRAUD" in keys
    assert "anumana:consortium:threat:cid:lane-a:tag:matched_rule:velocity_ip" in keys
    assert all(c.increment == 1 for c in cmds)


def test_apply_consortium_threat_counter_increments_uses_lua_script() -> None:
    async def _run() -> None:
        from orchestrator_analytics.consortium_threat_matrix import (
            ConsortiumThreatCounterCommand,
            apply_consortium_threat_counter_increments,
            verify_consortium_threat_counter_increments,
        )

        script = AsyncMock(return_value=1)
        redis_client = MagicMock()
        redis_client.register_script = MagicMock(return_value=script)

        pipe = MagicMock()
        pipe.get = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[b"3", b"5"])
        redis_client.pipeline = MagicMock(return_value=pipe)

        cmds = [
            ConsortiumThreatCounterCommand("anumana:consortium:threat:cid:global:labels_total", 1),
            ConsortiumThreatCounterCommand(
                "anumana:consortium:threat:cid:global:ground_truth:FRAUD", 1
            ),
        ]
        applied = await apply_consortium_threat_counter_increments(
            redis_client,
            cmds,
            consortium_id="global",
            label_id="label-1",
        )
        assert applied is True
        script.assert_awaited_once()
        verified = await verify_consortium_threat_counter_increments(redis_client, cmds)
        assert verified == [3, 5]

    asyncio.run(_run())


def test_consortium_counter_worker_acks_after_redis_and_clickhouse() -> None:
    async def _run() -> None:
        from messaging.labels_jetstream import NORMALIZED_LABEL_EVENT_SCHEMA
        from workers.consortium_counter_worker import (
            ConsortiumCounterDeps,
            process_consortium_label_message,
        )

        script = AsyncMock(return_value=1)
        redis_client = MagicMock()
        redis_client.register_script = MagicMock(return_value=script)

        pipe = MagicMock()
        pipe.get = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[b"1", b"1", b"1", b"1"])
        redis_client.pipeline = MagicMock(return_value=pipe)

        ch_client = MagicMock()
        ch_client.command = MagicMock()
        ch_client.query = MagicMock(return_value=SimpleNamespace(result_rows=[]))
        ch_client.insert = MagicMock()

        deps = ConsortiumCounterDeps(
            redis_client=redis_client,
            clickhouse_client=ch_client,
            consortium_id="global",
        )
        msg = SimpleNamespace(
            data=json.dumps(
                {
                    "schema": NORMALIZED_LABEL_EVENT_SCHEMA,
                    "id": "11111111-1111-1111-1111-111111111111",
                    "entity_id": "entity-1",
                    "ground_truth_class": "FRAUD",
                    "propagated_to_consortium": True,
                    "tags": ["vector:chargeback"],
                },
            ).encode("utf-8"),
            ack=AsyncMock(),
            nak=AsyncMock(),
        )

        with patch(
            "workers.consortium_counter_worker.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda fn, *args: fn(*args)),
        ):
            await process_consortium_label_message(deps, msg)

        redis_client.set.assert_not_called()
        script.assert_awaited_once()
        pipe.execute.assert_awaited_once()
        ch_client.command.assert_called()
        assert ch_client.insert.call_count == 2
        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()

    asyncio.run(_run())


def test_consortium_counter_worker_naks_on_clickhouse_failure() -> None:
    async def _run() -> None:
        from messaging.labels_jetstream import NORMALIZED_LABEL_EVENT_SCHEMA
        from workers.consortium_counter_worker import (
            ConsortiumCounterDeps,
            process_consortium_label_message,
        )

        script = AsyncMock(return_value=1)
        redis_client = MagicMock()
        redis_client.register_script = MagicMock(return_value=script)

        pipe = MagicMock()
        pipe.get = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[b"1", b"1", b"1"])
        redis_client.pipeline = MagicMock(return_value=pipe)

        ch_client = MagicMock()
        ch_client.command = MagicMock(side_effect=RuntimeError("clickhouse unavailable"))
        ch_client.query = MagicMock(return_value=SimpleNamespace(result_rows=[]))

        deps = ConsortiumCounterDeps(
            redis_client=redis_client,
            clickhouse_client=ch_client,
            consortium_id="global",
        )
        msg = SimpleNamespace(
            data=json.dumps(
                {
                    "schema": NORMALIZED_LABEL_EVENT_SCHEMA,
                    "id": "22222222-2222-2222-2222-222222222222",
                    "ground_truth_class": "LEGITIMATE",
                    "propagated_to_consortium": True,
                    "tags": [],
                },
            ).encode("utf-8"),
            ack=AsyncMock(),
            nak=AsyncMock(),
        )

        with patch(
            "workers.consortium_counter_worker.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda fn, *args: fn(*args)),
        ):
            await process_consortium_label_message(deps, msg)

        msg.nak.assert_awaited_once()
        msg.ack.assert_not_awaited()

    asyncio.run(_run())
