"""Graph structural signals: pure helpers + Sybil / IP_VELOCITY gate (optional Neo4j)."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from orchestrator.graph.client import (  # noqa: E402
    IP_VELOCITY_SYBIL_THRESHOLD,
    Neo4jGraphClient,
    ip_velocity_block,
    parse_graph_entity_ref,
)

NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI", "").strip()
NEO4J_TEST_USER = (os.environ.get("NEO4J_TEST_USER") or "neo4j").strip()
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD") or "password"


def test_parse_entity_ip_case_insensitive() -> None:
    assert parse_graph_entity_ref("ip:10.0.0.1") == ("ip", "10.0.0.1")
    assert parse_graph_entity_ref("IP:10.0.0.2") == ("ip", "10.0.0.2")
    assert parse_graph_entity_ref("user_1") == ("user", "user_1")


def test_ip_velocity_spike_crosses_threshold() -> None:
    block = ip_velocity_block(distinct_users_last_2h=10, threshold=IP_VELOCITY_SYBIL_THRESHOLD)
    assert block["distinct_users_last_2h"] == 10
    assert block["threshold"] == IP_VELOCITY_SYBIL_THRESHOLD
    assert block["spike"] is True
    assert block["score"] > 1.0


def test_ip_velocity_no_spike_at_threshold_boundary() -> None:
    block = ip_velocity_block(distinct_users_last_2h=IP_VELOCITY_SYBIL_THRESHOLD, threshold=IP_VELOCITY_SYBIL_THRESHOLD)
    assert block["spike"] is False


@pytest.mark.skipif(not NEO4J_TEST_URI, reason="NEO4J_TEST_URI not set")
def test_sybil_one_ip_ten_users_ip_velocity_spikes() -> None:
    """Sybil: many users on one IP ⇒ ``IP_VELOCITY`` spike (live Neo4j)."""
    from neo4j import AsyncGraphDatabase

    async def _run() -> None:
        drv = AsyncGraphDatabase.driver(
            NEO4J_TEST_URI,
            auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD),
        )
        try:
            await drv.execute_query("MATCH (n) DETACH DELETE n")
            client = Neo4jGraphClient(drv)
            now = datetime.now(UTC)
            ip = "ip_sybil_test"
            for i in range(10):
                t = TransactionSchema(
                    entity_id=uuid4(),
                    amount=float(i + 1),
                    timestamp=now,
                    metadata={"user_id": f"sybil_user_{i}", "ip": ip},
                )
                await client.ingest_transaction(t)

            signals = await client.get_graph_signals(f"ip:{ip}")
            assert signals["anchor"] == "ip"
            iv = signals["IP_VELOCITY"]
            assert iv["distinct_users_last_2h"] == 10
            assert iv["spike"] is True
            assert iv["score"] >= 10.0 / max(float(IP_VELOCITY_SYBIL_THRESHOLD), 1.0)
        finally:
            await drv.close()

    asyncio.run(_run())
