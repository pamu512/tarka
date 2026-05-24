"""Build ``POST /v1/analyze`` JSON with optional ``graph_context`` for Shadow Graph-RAG."""

from __future__ import annotations

import logging
from typing import Any

from ingestor.manifest_schema import TransactionSchema

from orchestrator.graph.client import GraphClient, JanusGraphClient, graph_hints_from_transaction

logger = logging.getLogger(__name__)


def _is_janusgraph_client(graph_client: GraphClient) -> bool:
    return isinstance(graph_client, JanusGraphClient)


def _topology_anchor_uid(uid: str | None, transaction: TransactionSchema) -> str | None:
    if uid:
        return uid
    entity_s = str(transaction.entity_id).strip()
    if entity_s and len(entity_s) <= 512 and "\x00" not in entity_s:
        return entity_s
    return None


def _shadow_user_id(meta: dict[str, Any]) -> str | None:
    for k in ("user_id", "graph_user_id", "user"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            s = v.strip()
            if len(s) <= 512 and "\x00" not in s:
                return s
    return None


async def build_shadow_analyze_payload(
    transaction: TransactionSchema,
    graph_client: GraphClient | None,
) -> dict[str, Any]:
    """
    Return ``{"transaction": …}`` plus ``graph_context`` when a graph client is configured.

    On ``SHADOW_REVIEW`` responses the orchestrator **awaits** ``graph_client.ingest_transaction`` (with
    DuckDB append in parallel via ``asyncio.gather``) before building this payload so topology reflects
    the current attempt while ``device_hardware_risk`` can still see prior accounts on shared hardware.
    For other outcomes those sidecars run as background tasks after the HTTP response is sent.
    """
    out: dict[str, Any] = {"transaction": transaction.model_dump(mode="json")}
    if graph_client is None:
        return out

    hints = graph_hints_from_transaction(transaction)
    meta = transaction.metadata or {}
    uid = _shadow_user_id(meta)
    ctx: dict[str, Any] = {}

    if uid:
        try:
            ctx["signals"] = await graph_client.get_graph_signals(uid)
        except Exception:
            logger.exception("orchestrator_shadow_graph_signals_failed transaction_id=%s", transaction.entity_id)

    if hints.device_id:
        try:
            ctx["device_hardware_graph"] = await graph_client.device_hardware_risk(
                hints.device_id,
                current_user_id=uid,
            )
        except Exception:
            logger.exception(
                "orchestrator_shadow_device_hardware_risk_failed transaction_id=%s",
                transaction.entity_id,
            )

    if _is_janusgraph_client(graph_client):
        anchor = _topology_anchor_uid(uid, transaction)
        if anchor:
            try:
                topology = await graph_client.two_hop_neighbor_network(anchor)
                if hints.ip:
                    try:
                        shared_ip_users = await graph_client.users_connected_to_ip(hints.ip)
                        topology = {
                            **topology,
                            "shared_ip_users_ordered_from": shared_ip_users,
                            "anchor_ip_address": hints.ip,
                        }
                    except Exception:
                        logger.exception(
                            "orchestrator_shadow_janus_shared_ip_users_failed transaction_id=%s",
                            transaction.entity_id,
                        )
                ctx["graph_topology"] = topology
            except Exception:
                logger.exception(
                    "orchestrator_shadow_janus_graph_topology_failed transaction_id=%s",
                    transaction.entity_id,
                )
        else:
            logger.warning(
                "orchestrator_shadow_janus_topology_skipped_no_anchor transaction_id=%s",
                transaction.entity_id,
            )

    if ctx:
        out["graph_context"] = ctx
    return out
