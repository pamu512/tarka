"""Gate: GraphIngestHandler payload validation and JanusGraph idempotency hooks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_graph_ingest_handler_requires_audit_log_id() -> None:
    async def _run() -> None:
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.graph_ingest import (
            GraphIngestHandler,
            GraphIngestPayloadError,
        )

        handler = GraphIngestHandler(
            OutboxProcessorDeps(session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None),
        )
        with pytest.raises(GraphIngestPayloadError, match="audit_log_id"):
            await handler.execute(
                {
                    "edge_transaction_payload_envelope": {
                        "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "amount": 1.0,
                        "timestamp": "2026-05-09T12:00:00+00:00",
                        "metadata": {},
                    },
                },
            )

    asyncio.run(_run())


def test_graph_ingest_handler_connection_drop_raises() -> None:
    async def _run() -> None:
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.graph_ingest import (
            GraphDatabaseConnectionError,
            GraphIngestHandler,
        )

        handler = GraphIngestHandler(
            OutboxProcessorDeps(session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None),
        )
        payload = {
            "audit_log_id": 42,
            "edge_transaction_payload_envelope": {
                "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "amount": 1.0,
                "timestamp": "2026-05-09T12:00:00+00:00",
                "metadata": {"user_id": "u1", "device_id": "d1"},
            },
        }
        fake_client = SimpleNamespace(_g=MagicMock(), close=MagicMock(return_value=None))

        async def _close() -> None:
            return None

        fake_client.close = _close

        with patch(
            "orchestrator.workers.handlers.graph_ingest._connect_janusgraph",
            return_value=fake_client,
        ):
            with patch(
                "orchestrator.workers.handlers.graph_ingest._ingest_janus_sync",
                side_effect=ConnectionResetError("connection dropped"),
            ):
                with pytest.raises(GraphDatabaseConnectionError):
                    await handler.execute(payload)

    asyncio.run(_run())


def test_ingest_already_committed_short_circuits() -> None:
    from orchestrator.workers.handlers.graph_ingest import _ingest_already_committed

    client = SimpleNamespace(_g=MagicMock())
    client._g.E.return_value = client._g
    client._g.has.return_value = client._g
    client._g.limit.return_value = client._g
    client._g.count.return_value = client._g
    client._g.next.return_value = 1

    assert _ingest_already_committed(client, transaction_id="tx-1", audit_log_id=7) is True
