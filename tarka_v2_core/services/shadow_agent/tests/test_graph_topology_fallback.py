"""Unit tests: orchestrator ``graph_topology`` → ``find_linked_entities`` summary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from ingestor.schemas import TransactionSchema
from shadow_agent.graph_tool import find_linked_entities_from_topology


def test_find_linked_entities_from_topology_formats_janus_network() -> None:
    tx = TransactionSchema(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=88.0,
        timestamp=datetime(2026, 3, 1, tzinfo=UTC),
        metadata={"user_id": "u1", "ip": "10.0.0.1"},
    )
    summary = find_linked_entities_from_topology(
        str(tx.entity_id),
        tx,
        {
            "found": True,
            "anchor_user_id": "u1",
            "network_user_ids": ["u1", "u2"],
            "network_device_ids": ["d1"],
            "network_ip_addresses": ["10.0.0.1"],
            "blocked_device_touch_count": 1,
            "neighbor_node_count": 2,
            "backend": "janusgraph",
            "shared_ip_users_ordered_from": ["u2", "u3"],
        },
    )
    assert "orchestrator graph_topology" in summary
    assert "u2" in summary
    assert "ORDERED_FROM_IP" in summary
    assert "Device neighbors: d1" in summary
