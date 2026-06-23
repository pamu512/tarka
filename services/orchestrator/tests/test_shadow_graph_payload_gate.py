"""Gate: JanusGraph backend injects ``graph_topology`` into Shadow analyze payloads."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from shadow_graph_payload import build_shadow_analyze_payload  # noqa: E402


class _FakeJanusGraphClient:
    """Minimal async graph client behavior for Janus topology injection tests."""

    async def get_graph_signals(self, entity_id: str) -> dict[str, object]:
        return {"backend": "janusgraph", "entity_ref": entity_id}

    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, object]:
        _ = current_user_id
        return {"device_id": device_id, "linked_to_blocked_node": False}

    async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, object]:
        return {
            "found": True,
            "anchor_user_id": anchor_user_id,
            "network_user_ids": [anchor_user_id, "peer_u1"],
            "network_device_ids": ["dev_a"],
            "network_ip_addresses": ["203.0.113.10"],
            "blocked_device_touch_count": 1,
            "neighbor_node_count": 3,
            "edges_summary": [],
            "backend": "janusgraph",
        }

    async def users_connected_to_ip(self, ip: str) -> list[str]:
        _ = ip
        return ["peer_u1", "peer_u2"]


def test_build_shadow_analyze_payload_janus_injects_graph_topology() -> None:
    from graph.client import JanusGraphClient  # noqa: PLC0415

    class _JanusStub(JanusGraphClient):
        def __init__(self) -> None:
            pass

        async def get_graph_signals(self, entity_id: str) -> dict[str, object]:
            return await client.get_graph_signals(entity_id)

        async def device_hardware_risk(
            self,
            device_id: str,
            *,
            current_user_id: str | None = None,
        ) -> dict[str, object]:
            return await client.device_hardware_risk(device_id, current_user_id=current_user_id)

        async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, object]:
            return await client.two_hop_neighbor_network(anchor_user_id)

        async def users_connected_to_ip(self, ip: str) -> list[str]:
            return await client.users_connected_to_ip(ip)

        async def ingest_transaction(self, transaction: TransactionSchema) -> None:
            return None

        async def close(self) -> None:
            return None

    client = _FakeJanusGraphClient()
    janus = _JanusStub()
    tx = TransactionSchema(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=120.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata={"user_id": "u_janus", "ip": "203.0.113.10", "device_id": "dev_x"},
    )

    async def _run() -> dict[str, object]:
        return await build_shadow_analyze_payload(tx, janus)

    payload = asyncio.run(_run())
    ctx = payload.get("graph_context")
    assert isinstance(ctx, dict)
    topo = ctx.get("graph_topology")
    assert isinstance(topo, dict)
    assert topo.get("backend") == "janusgraph"
    assert topo.get("anchor_user_id") == "u_janus"
    assert "peer_u1" in (topo.get("network_user_ids") or [])
    assert topo.get("shared_ip_users_ordered_from") == ["peer_u1", "peer_u2"]
