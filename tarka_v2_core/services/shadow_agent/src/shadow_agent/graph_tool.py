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

from shadow_agent.graph_hints import graph_anchor_hints

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


async def find_linked_entities(entity_id: str, tx: TransactionSchema, driver: Any) -> str:
    """
    Execute an undirected **≤N-hop** neighborhood expansion (``GRAPH_MAX_HOPS``) from the
    transaction's graph anchors (``User`` / ``IP`` / ``Device``) and return a compact text summary.

    ``entity_id`` is the canonical transaction UUID string used for logging / audit correlation.
    """
    hints = graph_anchor_hints(tx)
    if hints.user_id is None and hints.ip is None and hints.device_id is None:
        return (
            f"find_linked_entities({entity_id}): no graph anchors in metadata "
            f"(need user_id, ip, and/or device_id)."
        )

    nh = _neighbor_max_hops_from_env()
    q = f"""
    MATCH (n)
    WHERE (n:`{LABEL_USER}` AND $uid IS NOT NULL AND n.user_id = $uid)
       OR (n:`{LABEL_IP}` AND $addr IS NOT NULL AND n.address = $addr)
       OR (n:`{LABEL_DEVICE}` AND $did IS NOT NULL AND n.device_id = $did)
    WITH collect(DISTINCT n) AS roots
    UNWIND roots AS root
    MATCH (root)-[*1..{nh}]-(h2)
    WHERE h2 <> root
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

    q_shared_ip = f"""
    MATCH (ip:{LABEL_IP} {{address: $addr}})<-[:{REL_ORDERED_FROM_IP}]-(u:{LABEL_USER})
    RETURN collect(DISTINCT u.user_id) AS users
    """

    async def work_shared_ip(txn: Any) -> list[str]:
        result = await txn.run(q_shared_ip, addr=hints.ip)
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
