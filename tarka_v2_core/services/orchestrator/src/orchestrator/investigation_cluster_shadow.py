"""Knowledge Drop → JanusGraph two-hop + DuckDB cluster velocity → Shadow ``/v1/analyze`` context."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncio

from orchestrator.graph.client import GraphClient

if TYPE_CHECKING:
    from orchestrator.analytics.provider import AnalyticsProvider

logger = logging.getLogger(__name__)


def synthetic_dispute_transaction(*, anchor_id: str, filename: str) -> dict[str, Any]:
    """Synthetic envelope so Shadow can run structured ``ShadowDecision`` on a knowledge-drop dispute."""
    return {
        "entity_id": str(uuid.uuid4()),
        "amount": 1.0,
        "timestamp": datetime.now(UTC).isoformat(),
        "metadata": {
            "knowledge_drop_anchor": anchor_id,
            "knowledge_drop_filename": filename,
            "knowledge_drop_kind": "dispute_cluster_review",
        },
        "country": None,
    }


def build_cluster_analyst_instruction(anchor_id: str, net: dict[str, Any], duck: dict[str, Any]) -> str:
    """Narrative framing passed to Shadow (also echoed in ``graph_context`` for the LLM)."""
    bd = int(net.get("blocked_device_touch_count") or 0)
    spike_pct = duck.get("spike_pct_vs_flat_baseline_2h")
    if spike_pct is None:
        spike_txt = "an elevated"
    else:
        try:
            spike_txt = f"a {float(spike_pct):.0f}%"
        except (TypeError, ValueError):
            spike_txt = "an elevated"
    return (
        f"Analyst has uploaded a dispute for ID {anchor_id}. "
        f"Graph shows this ID is linked to {bd} blocked devices. "
        f"DuckDB shows {spike_txt} spike in spend across this cluster in 2 hours. "
        "Analyze the coordination risk."
    )


async def build_prime_shadow_graph_context(
    anchor_id: str,
    *,
    graph_client: GraphClient,
    analytics: AnalyticsProvider | None,
) -> dict[str, Any]:
    """
    Parallel graph linkage probe + two-hop neighborhood, then analytics-plane velocity for that network.

    Intended for ``POST …/v1/analyze`` ``graph_context`` so Shadow cites topology and spend metrics.
    """
    net_task = graph_client.two_hop_neighbor_network(anchor_id)
    link_task = graph_client.knowledge_linked_users(anchor_id)
    net, linked = await asyncio.gather(net_task, link_task)

    duck_payload: dict[str, Any] = {}
    if analytics is not None:
        duck_payload = await asyncio.to_thread(
            analytics.cluster_spend_velocity_for_network,
            transaction_entity_ids=list(net.get("network_transaction_ids") or ()),
            network_user_ids=list(net.get("network_user_ids") or ()),
            days=30,
        )

    instruction = build_cluster_analyst_instruction(anchor_id, net, duck_payload)
    return {
        "two_hop_network": net,
        "knowledge_link_probe": linked,
        "duck_spend_velocity_30d": duck_payload,
        "cluster_analyst_instruction": instruction,
    }
