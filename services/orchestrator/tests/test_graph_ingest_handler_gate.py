"""Gate: GraphIngestHandler payload validation and JanusGraph idempotency hooks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_graph_ingest_handler_requires_audit_log_id() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.graph_ingest import (
            GraphIngestHandler,
            GraphIngestPayloadError,
        )

        handler = GraphIngestHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None
            ),
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


def test_ingest_from_event_no_tenant_returns_reason_not_write() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.graph_ingest import GraphIngestHandler

        handler = GraphIngestHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None
            ),
        )
        reason = await handler.execute(
            {
                "audit_log_id": 7,
                "event": {"entity_id": "tx-1", "payload": {"device_id": "d1", "user_id": "u1"}},
            }
        )
        assert reason == "noop:no_tenant"

    asyncio.run(_run())


def test_graph_ingest_non_200_raises() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.graph_ingest import (
            GraphDatabaseConnectionError,
            GraphIngestHandler,
        )

        class _Http:
            async def __aenter__(self) -> _Http:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, json: object) -> object:
                return type("R", (), {"status_code": 503})()

        handler = GraphIngestHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None
            ),
        )
        with patch(
            "workers.handlers.graph_ingest.httpx.AsyncClient",
            lambda *args, **kwargs: _Http(),
        ):
            with pytest.raises(GraphDatabaseConnectionError):
                await handler.execute(
                    {
                        "audit_log_id": 7,
                        "event": {
                            "tenant_id": "acme",
                            "entity_id": "tx-1",
                            "payload": {"user_id": "u1", "device_id": "d1"},
                        },
                    }
                )

    asyncio.run(_run())


def test_ingest_from_event_no_hints_returns_reason() -> None:
    async def _run() -> None:
        from graph.client import NullGraphClient
        from workers.handlers.base import OutboxProcessorDeps
        from workers.handlers.graph_ingest import GraphIngestHandler

        handler = GraphIngestHandler(
            OutboxProcessorDeps(
                session_factory=MagicMock(), graph_client=NullGraphClient(), redis_client=None
            ),
        )
        reason = await handler.execute(
            {
                "audit_log_id": 7,
                "event": {"tenant_id": "acme", "entity_id": "tx-1", "payload": {}},
            }
        )
        assert reason == "noop:no_graph_hints"

    asyncio.run(_run())
