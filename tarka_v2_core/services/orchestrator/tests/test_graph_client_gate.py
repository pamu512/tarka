"""
Gate (Neo4j): two transactions share ``ip``; ``users_connected_to_ip`` returns both users.

Requires a running Bolt endpoint and ``NEO4J_TEST_URI`` (e.g. ``bolt://127.0.0.1:7687``).
Optional: ``NEO4J_TEST_USER``, ``NEO4J_TEST_PASSWORD`` (defaults ``neo4j`` / ``password``).

Example::

    docker run --rm -p 7687:7687 -p 7474:7474 \\
      -e NEO4J_AUTH=neo4j/password \\
      neo4j:5-community
    export NEO4J_TEST_URI=bolt://127.0.0.1:7687
    pytest tarka_v2_core/services/orchestrator/tests/test_graph_client_gate.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from orchestrator.graph.client import Neo4jGraphClient  # noqa: E402

NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI", "").strip()
NEO4J_TEST_USER = (os.environ.get("NEO4J_TEST_USER") or "neo4j").strip()
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD") or "password"


@pytest.mark.skipif(not NEO4J_TEST_URI, reason="NEO4J_TEST_URI not set (live Neo4j gate)")
def test_gate_two_users_share_ip_query_returns_both() -> None:
    from neo4j import AsyncGraphDatabase

    async def _run() -> None:
        drv = AsyncGraphDatabase.driver(
            NEO4J_TEST_URI,
            auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD),
        )
        try:
            await drv.execute_query("MATCH (n) DETACH DELETE n")

            client = Neo4jGraphClient(drv)
            t1 = TransactionSchema(
                entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                amount=11.0,
                timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
                metadata={"user_id": "user_1", "ip": "ip_A"},
            )
            t2 = TransactionSchema(
                entity_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                amount=22.0,
                timestamp=datetime(2026, 5, 9, 12, 1, 0, tzinfo=UTC),
                metadata={"user_id": "user_2", "ip": "ip_A"},
            )
            await client.ingest_transaction(t1)
            await client.ingest_transaction(t2)
            users = await client.users_connected_to_ip("ip_A")
            assert users == ["user_1", "user_2"]
        finally:
            await drv.close()

    asyncio.run(_run())
