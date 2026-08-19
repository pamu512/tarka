"""
Graph tool: ``find_linked_entities`` — 2-hop neighborhood probe for Shadow Review triage.

Uses Neo4j Bolt when ``SHADOW_GRAPH_NEO4J_URI`` / ``NEO4J_URI`` / ``GRAPH_NEO4J_URI`` is configured
(same graph schema as the orchestrator :mod:`orchestrator.graph.client`).

Env:

* ``SHADOW_GRAPH_TOOL_MODE`` — ``off`` | ``heuristic`` (default) | ``always``
* ``SHADOW_GRAPH_TOOL_AMOUNT_MIN`` / ``SHADOW_GRAPH_TOOL_AMOUNT_MAX`` — borderline band for heuristic mode
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ingestor.schemas import TransactionSchema

from graph_hints import graph_anchor_hints

logger = logging.getLogger(__name__)


def _neighbor_max_hops_from_env() -> int:
    """Aligned with orchestrator :mod:`orchestrator.graph.client` (``GRAPH_MAX_HOPS`` / deploy profile)."""
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().graph_neighbor_max_hops
    except Exception:
        raw = (os.environ.get("GRAPH_MAX_HOPS") or "").strip()
        if raw.isdigit():
            v = int(raw)
            return max(1, min(v, 16))
        return 2


LABEL_USER = "User"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
LABEL_CARD = "Card"
LABEL_EMAIL = "Email"
LABEL_ADDRESS = "Address"

REL_USED_DEVICE = "USED_DEVICE"
REL_ORDERED_FROM_IP = "ORDERED_FROM_IP"
REL_PAID_WITH_CARD = "PAID_WITH_CARD"


def neo4j_driver_from_env() -> Any | None:
    """Return a Neo4j async driver or ``None`` when graph is not configured for this process."""
    try:
        from neo4j import AsyncGraphDatabase
    except ImportError:
        logger.warning("shadow_graph_tool_neo4j_driver_missing")
        return None

    uri = (
        os.environ.get("SHADOW_GRAPH_NEO4J_URI", "").strip()
        or os.environ.get("NEO4J_URI", "").strip()
        or os.environ.get("GRAPH_NEO4J_URI", "").strip()
    )
    if not uri:
        return None
    user = (os.environ.get("NEO4J_USER") or os.environ.get("GRAPH_NEO4J_USER") or "neo4j").strip()
    password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GRAPH_NEO4J_PASSWORD") or ""
    try:
        return AsyncGraphDatabase.driver(uri, auth=(user, password))
    except Exception:
        logger.exception("shadow_graph_tool_neo4j_driver_init_failed")
        return None


def graph_tool_mode() -> str:
    return (os.environ.get("SHADOW_GRAPH_TOOL_MODE") or "heuristic").strip().lower()


def should_run_graph_tool_heuristic(
    tx: TransactionSchema, graph_context: dict[str, Any] | None
) -> bool:
    """
    Borderline Shadow Review heuristic: amount in a mid band **and** an IP is present for
    shared-IP history probing.
    """
    hints = graph_anchor_hints(tx)
    if hints.ip is None:
        return False
    lo = float(os.environ.get("SHADOW_GRAPH_TOOL_AMOUNT_MIN", "45"))
    hi = float(os.environ.get("SHADOW_GRAPH_TOOL_AMOUNT_MAX", "155"))
    if not (lo <= float(tx.amount) <= hi):
        return False
    # If orchestrator already shipped a rich IP_VELOCITY spike, skip redundant probe (optional).
    if graph_context:
        ip_vel = graph_context.get("IP_VELOCITY") if isinstance(graph_context, dict) else None
        if isinstance(ip_vel, dict) and ip_vel.get("spike") is True:
            return False
    return True


def wants_find_linked_entities(
    tx: TransactionSchema,
    graph_context: dict[str, Any] | None,
) -> bool:
    """True when policy says Shadow should run the graph probe (independent of Neo4j driver availability)."""
    mode = graph_tool_mode()
    if mode in ("off", "disabled", "false", "0"):
        return False
    if mode == "always":
        return True
    return should_run_graph_tool_heuristic(tx, graph_context)


def should_invoke_find_linked_entities(
    tx: TransactionSchema,
    graph_context: dict[str, Any] | None,
    *,
    driver_available: bool,
) -> bool:
    return wants_find_linked_entities(tx, graph_context) and driver_available


def orchestrator_graph_topology(graph_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return orchestrator-injected ``graph_topology`` when present and dict-shaped."""
    if not isinstance(graph_context, dict):
        return None
    topo = graph_context.get("graph_topology")
    return topo if isinstance(topo, dict) else None


def find_linked_entities_from_topology(
    entity_id: str,
    tx: TransactionSchema,
    topology: dict[str, Any],
) -> str:
    """
    Build a ``find_linked_entities``-compatible summary from orchestrator ``graph_topology``.

    Used when JanusGraph (Gremlin) supplies neighborhood data on the ingest payload and the
    Shadow process has no local Neo4j driver.
    """
    hints = graph_anchor_hints(tx)
    nh = _neighbor_max_hops_from_env()
    backend = str(topology.get("backend") or "orchestrator_topology")
    anchor_user = str(topology.get("anchor_user_id") or hints.user_id or "").strip()

    users_raw = topology.get("network_user_ids")
    devices_raw = topology.get("network_device_ids")
    ips_raw = topology.get("network_ip_addresses")
    users = (
        sorted({str(u) for u in users_raw if u is not None and str(u).strip()})
        if isinstance(users_raw, list)
        else []
    )
    devices = (
        sorted({str(d) for d in devices_raw if d is not None and str(d).strip()})
        if isinstance(devices_raw, list)
        else []
    )
    ips = (
        sorted({str(i) for i in ips_raw if i is not None and str(i).strip()})
        if isinstance(ips_raw, list)
        else []
    )

    blocked_device_touch = int(topology.get("blocked_device_touch_count") or 0)
    neighbor_count = int(topology.get("neighbor_node_count") or 0)
    found = bool(topology.get("found"))

    lines = [
        f"find_linked_entities({entity_id}): ≤{nh}-hop neighborhood from orchestrator graph_topology "
        f"(backend={backend!r}).",
        f"Anchors: user_id={hints.user_id!r}, ip={hints.ip!r}, device_id={hints.device_id!r}.",
        f"Topology anchor_user_id={anchor_user!r}, found={found}, neighbor_node_count={neighbor_count}, "
        f"blocked_device_touch_count={blocked_device_touch}.",
    ]

    if not found and not users and not devices and not ips:
        lines.append(
            f"≤{nh}-hop: orchestrator topology empty (anchor may be absent in graph store).",
        )

    if hints.user_id:
        peer_users = sorted(u for u in users if u and u != hints.user_id)
    else:
        peer_users = users
    lines.append(
        "Shared user neighborhood (network_user_ids): "
        + (", ".join(peer_users) if peer_users else "(none besides anchors)"),
    )

    shared_ip_ordered = topology.get("shared_ip_users_ordered_from")
    if hints.ip:
        if isinstance(shared_ip_ordered, list):
            ordered = sorted(
                str(u)
                for u in shared_ip_ordered
                if u is not None
                and str(u).strip()
                and (hints.user_id is None or str(u) != hints.user_id)
            )
            lines.append(
                "Shared IP history (ORDERED_FROM_IP — distinct User.user_id on this IP): "
                + (", ".join(ordered) if ordered else "(none besides current user)"),
            )
        else:
            ip_peers = sorted(u for u in peer_users if u)
            lines.append(
                f"Shared IP history (users in topology near ip={hints.ip!r}): "
                + (", ".join(ip_peers) if ip_peers else "(none besides anchors)"),
            )

    if devices:
        sample = devices[:25]
        tail = " …" if len(devices) > 25 else ""
        lines.append(f"Device neighbors: {', '.join(sample)}{tail}")
    if ips:
        sample = ips[:25]
        tail = " …" if len(ips) > 25 else ""
        lines.append(f"IP neighbors: {', '.join(sample)}{tail}")

    edges = topology.get("edges_summary")
    if isinstance(edges, list) and edges:
        edge_sample = [str(e) for e in edges[:10] if e is not None and str(e).strip()]
        if edge_sample:
            lines.append("Edge samples: " + "; ".join(edge_sample))

    return "\n".join(lines)


async def find_linked_entities(
    entity_id: str,
    tx: TransactionSchema,
    driver: Any,
    *,
    tenant_id: str | None = None,
) -> str:
    """
    Execute an undirected **≤N-hop** neighborhood expansion (``GRAPH_MAX_HOPS``) from the
    transaction's graph anchors (``User`` / ``IP`` / ``Device``) and return a compact text summary.

    ``entity_id`` is the canonical transaction UUID string used for logging / audit correlation.
    When ``tenant_id`` is set, Neo4j nodes are restricted to that tenant. When
    ``TENANT_BINDING_REQUIRED`` is on, ``tenant_id`` is required (fail closed).
    """
    from shadow_tenant import require_tenant_for_read

    scoped_tenant = require_tenant_for_read(tenant_id)
    hints = graph_anchor_hints(tx)
    if hints.user_id is None and hints.ip is None and hints.device_id is None:
        return (
            f"find_linked_entities({entity_id}): no graph anchors in metadata "
            f"(need user_id, ip, and/or device_id)."
        )

    nh = _neighbor_max_hops_from_env()
    tenant_root = " AND n.tenant_id = $tenant_id" if scoped_tenant is not None else ""
    tenant_hop = " AND h2.tenant_id = $tenant_id" if scoped_tenant is not None else ""
    q = f"""
    MATCH (n)
    WHERE ((n:`{LABEL_USER}` AND $uid IS NOT NULL AND n.user_id = $uid)
       OR (n:`{LABEL_IP}` AND $addr IS NOT NULL AND n.address = $addr)
       OR (n:`{LABEL_DEVICE}` AND $did IS NOT NULL AND n.device_id = $did)){tenant_root}
    WITH collect(DISTINCT n) AS roots
    UNWIND roots AS root
    MATCH (root)-[*1..{nh}]-(h2)
    WHERE h2 <> root{tenant_hop}
    RETURN DISTINCT head(labels(h2)) AS lbl,
           coalesce(
             h2.user_id,
             h2.address,
             h2.device_id,
             h2.card_id,
             h2.email,
             h2.line1,
             elementId(h2)
           ) AS ext
    LIMIT 200
    """

    async def work(txn: Any) -> list[dict[str, Any]]:
        result = await txn.run(
            q,
            uid=hints.user_id,
            addr=hints.ip,
            did=hints.device_id,
            tenant_id=scoped_tenant,
        )
        rows: list[dict[str, Any]] = []
        async for rec in result:
            rows.append(
                {
                    "lbl": rec.get("lbl"),
                    "ext": rec.get("ext"),
                },
            )
        return rows

    tenant_ip = (
        " WHERE ip.tenant_id = $tenant_id AND u.tenant_id = $tenant_id"
        if scoped_tenant is not None
        else ""
    )
    q_shared_ip = f"""
    MATCH (ip:{LABEL_IP} {{address: $addr}})<-[:{REL_ORDERED_FROM_IP}]-(u:{LABEL_USER}){tenant_ip}
    RETURN collect(DISTINCT u.user_id) AS users
    """

    async def work_shared_ip(txn: Any) -> list[str]:
        result = await txn.run(q_shared_ip, addr=hints.ip, tenant_id=scoped_tenant)
        rec = await result.single()
        if rec is None:
            return []
        users = rec.get("users")
        if users is None:
            return []
        return [str(u) for u in users if u is not None and str(u).strip()]

    shared_ip_accounts: list[str] = []
    async with driver.session() as session:
        rows = await session.execute_read(work)
        if hints.ip:
            shared_ip_accounts = await session.execute_read(work_shared_ip)

    by_label: dict[str, list[str]] = {}
    ip_neighbors: set[str] = set()
    user_neighbors: set[str] = set()
    for row in rows:
        lbl = str(row.get("lbl") or "?")
        ext = str(row.get("ext") or "")
        if not ext:
            continue
        by_label.setdefault(lbl, []).append(ext)
        if lbl == LABEL_IP:
            ip_neighbors.add(ext)
        if lbl == LABEL_USER:
            user_neighbors.add(ext)

    lines = [
        f"find_linked_entities({entity_id}): ≤{nh}-hop neighborhood (max 200 nodes sampled).",
        f"Anchors: user_id={hints.user_id!r}, ip={hints.ip!r}, device_id={hints.device_id!r}.",
    ]
    if not rows:
        lines.append(
            f"≤{nh}-hop: no neighbor rows in this sample (anchors may exist but have no matches in this depth).",
        )
    if hints.ip:
        shared = sorted(
            u for u in user_neighbors if u and (hints.user_id is None or u != hints.user_id)
        )
        lines.append(
            f"Shared IP history (users seen within {nh} hops of this IP anchor): "
            + (", ".join(shared) if shared else "(none besides anchors)"),
        )
        ordered = sorted(
            u for u in shared_ip_accounts if u and (hints.user_id is None or u != hints.user_id)
        )
        lines.append(
            "Shared IP history (ORDERED_FROM_IP — distinct User.user_id on this IP): "
            + (", ".join(ordered) if ordered else "(none besides current user)"),
        )
    for lbl, ids in sorted(by_label.items()):
        uniq = sorted(frozenset(ids))[:25]
        tail = " …" if len(frozenset(ids)) > 25 else ""
        lines.append(f"{lbl} neighbors: {', '.join(uniq)}{tail}")
    return "\n".join(lines)
