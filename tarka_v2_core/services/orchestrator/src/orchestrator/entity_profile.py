"""Unified **Entity Explorer** payload: Postgres lifecycle case + graph fragment + analytics plane + optional Shadow."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from ingestor.manifest_schema import TransactionSchema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.analytics.provider import AnalyticsProvider
from orchestrator.graph.client import GraphClient
from orchestrator.models.cases import CaseORM, CaseStatus

logger = logging.getLogger(__name__)


def build_graph_viz(user_id: str, network: dict[str, Any]) -> dict[str, Any]:
    """Normalize JanusGraph / Neo4j ``two_hop_neighbor_network`` into nodes + links for the UI."""
    uid = (user_id or "").strip()
    nodes: list[dict[str, str]] = [{"id": f"user:{uid}", "kind": "User", "label": uid}]
    links: list[dict[str, str]] = []
    anchor = f"user:{uid}"
    for d in (network.get("network_device_ids") or [])[:24]:
        nid = f"device:{d}"
        nodes.append({"id": nid, "kind": "Device", "label": str(d)})
        links.append({"source": anchor, "target": nid, "rel": "USED_DEVICE"})
    for ip in (network.get("network_ip_addresses") or [])[:24]:
        nid = f"ip:{ip}"
        nodes.append({"id": nid, "kind": "IP", "label": str(ip)})
        links.append({"source": anchor, "target": nid, "rel": "ORDERED_FROM_IP"})
    return {
        "nodes": nodes,
        "links": links,
        "backend": network.get("backend"),
        "found": bool(network.get("found")),
    }


async def _load_lifecycle_case(
    fac: async_sessionmaker[AsyncSession] | None,
    user_id: str,
) -> dict[str, Any] | None:
    if fac is None:
        return None
    async with fac() as session:
        row = (
            await session.execute(
                select(CaseORM)
                .where(CaseORM.user_link_key == user_id)
                .order_by(CaseORM.opened_at.desc())
                .limit(1),
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    try:
        st = CaseStatus(str(row.status))
        status_s = st.value
    except ValueError:
        status_s = str(row.status)
    return {
        "source": "postgres",
        "case_id": str(row.case_id),
        "status": status_s,
        "priority": int(row.priority),
        "entity_id": str(row.entity_id),
        "transaction_id": int(row.transaction_id),
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
    }


async def _shadow_executive_summary(
    *,
    user_id: str,
    graph_context: dict[str, Any],
    shadow_base: str,
    shadow_key: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    probe_id = uuid5(NAMESPACE_URL, f"tarka:entity-profile:{user_id}")
    tx = TransactionSchema(
        entity_id=probe_id,
        amount=1.0,
        timestamp=datetime.now(UTC),
        metadata={
            "user_id": user_id,
            "entity_profile_probe": True,
            "channel": "entity_explorer",
        },
    )
    body: dict[str, Any] = {
        "transaction": tx.model_dump(mode="json"),
        "graph_context": graph_context,
    }
    headers: dict[str, str] = {}
    if shadow_key:
        headers["X-Shadow-Token"] = shadow_key
    url = f"{shadow_base.rstrip('/')}/v1/analyze"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            r = await client.post(url, json=body, headers=headers or None)
    except httpx.RequestError as exc:
        logger.warning("entity_profile_shadow_transport_failed user_id=%s err=%s", user_id, exc)
        return {
            "source": "shadow",
            "available": False,
            "error": "shadow_transport_error",
            "message": str(exc),
        }
    try:
        data = r.json()
    except json.JSONDecodeError:
        data = {}
    if r.status_code >= 400:
        return {
            "source": "shadow",
            "available": False,
            "error": "shadow_http_error",
            "status_code": r.status_code,
            "message": str(data.get("detail", data))[:2048],
        }
    return {
        "source": "shadow",
        "available": True,
        "ai_reasoning": str(data.get("ai_reasoning") or "").strip(),
        "risk_score": data.get("risk_score"),
        "is_fraud": data.get("is_fraud"),
        "reasoning": data.get("reasoning"),
    }


async def build_entity_profile_payload(
    *,
    user_id: str,
    audit_session_factory: async_sessionmaker[AsyncSession] | None,
    graph_client: GraphClient,
    analytics: AnalyticsProvider | None,
    shadow_base: str | None,
    shadow_key: str | None,
    shadow_timeout_s: float,
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("empty user_id")

    lifecycle = await _load_lifecycle_case(audit_session_factory, uid)
    network = await graph_client.two_hop_neighbor_network(uid)
    graph_viz = build_graph_viz(uid, network)

    duck_metrics: dict[str, Any]
    if analytics is None:
        duck_metrics = {
            "source": "duckdb",
            "available": False,
            "error": "analytics_unavailable",
        }
    else:
        duck_metrics = {**analytics.marketplace_user_stats(uid), "available": True}
        devs = [
            str(d).strip()
            for d in (network.get("network_device_ids") or [])
            if isinstance(d, str) and str(d).strip()
        ][:8]
        if devs:
            cl = analytics.cluster_loss_for_device_hashes(devs)
            duck_metrics["cluster_loss"] = cl["cluster_loss"]
            duck_metrics["cluster_loss_txn_count"] = cl["linked_txn_count"]
            duck_metrics["cluster_loss_session_count"] = cl["distinct_session_count"]
            duck_metrics["cluster_loss_device_scope"] = cl["device_hashes_used"]

    graph_ctx_for_shadow: dict[str, Any] = {
        "two_hop_network": network,
        "entity_profile_duck_metrics": duck_metrics,
    }
    if analytics is not None:
        graph_ctx_for_shadow["duck_spend_velocity_30d"] = analytics.cluster_spend_velocity_for_network(
            transaction_entity_ids=[],
            network_user_ids=[uid],
        )

    skip_shadow = (os.environ.get("ORCHESTRATOR_ENTITY_PROFILE_SKIP_SHADOW") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    shadow_summary: dict[str, Any]
    if skip_shadow or not (shadow_base and str(shadow_base).strip()):
        shadow_summary = {
            "source": "shadow",
            "available": False,
            "skipped": bool(skip_shadow),
            "error": "shadow_not_configured_or_skipped",
        }
    else:
        shadow_summary = await _shadow_executive_summary(
            user_id=uid,
            graph_context=graph_ctx_for_shadow,
            shadow_base=str(shadow_base).strip(),
            shadow_key=shadow_key,
            timeout_s=max(5.0, float(shadow_timeout_s)),
        )

    return {
        "user_id": uid,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_sources": {
            "postgres_queried": audit_session_factory is not None,
            "postgres_case_row": lifecycle is not None,
            "graph_backend": str(network.get("backend") or "none"),
            "graph_neighbors_found": bool(network.get("found")),
            "duckdb": analytics is not None,
            "shadow_live": bool(shadow_summary.get("available")),
        },
        "lifecycle_case": lifecycle,
        "graph_fragment": network,
        "graph_viz": graph_viz,
        "duckdb_metrics": duck_metrics,
        "shadow_executive_summary": shadow_summary,
    }
