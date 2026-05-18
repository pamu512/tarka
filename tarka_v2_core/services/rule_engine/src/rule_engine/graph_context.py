"""Graph-backed values for rule evaluation (Neo4j Bolt, same env vars as the orchestrator graph)."""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from ingestor.manifest_schema import TransactionSchema

from rule_engine.ast_schemas import AndNode, ConditionNode, LogicalNode, OrNode, Rule

logger = logging.getLogger(__name__)

GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD = "graph_linked_to_blocked_count"
GRAPH_CONTEXT_FAIL_OPEN_KEY = "_graph_context_fail_open"


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        raw = meta.get(k)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            s = str(raw).strip()
        elif isinstance(raw, str):
            s = raw.strip()
        else:
            continue
        if not s or len(s) > 512 or "\x00" in s:
            continue
        return s
    return None


def logical_node_uses_graph_field(node: LogicalNode) -> bool:
    if isinstance(node, ConditionNode):
        return node.field.field == GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD
    if isinstance(node, (AndNode, OrNode)):
        return any(logical_node_uses_graph_field(c) for c in node.children)
    return False


def ruleset_needs_graph_context(rules: tuple[Rule, ...]) -> bool:
    return any(logical_node_uses_graph_field(r.root_node) for r in rules)


class GraphContextProvider(Protocol):
    async def fetch_graph_context(self, transaction: TransactionSchema) -> dict[str, Any]:
        """Return keys merged into the evaluator (e.g. ``graph_linked_to_blocked_count``)."""


class NullGraphContextProvider:
    async def fetch_graph_context(self, transaction: TransactionSchema) -> dict[str, Any]:
        _ = transaction
        return {GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD: 0}


class Neo4jGraphContextProvider:
    """
    Count distinct **blocked** ``User`` nodes sharing the same ``IP`` as the current user
    (via ``ORDERED_FROM_IP``), excluding the subject user.
    """

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    @classmethod
    def try_from_env(cls) -> Neo4jGraphContextProvider | None:
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError:
            logger.warning("rule_engine_neo4j_import_missing")
            return None

        uri = (os.environ.get("NEO4J_URI") or os.environ.get("GRAPH_NEO4J_URI") or "").strip()
        if not uri:
            return None
        user = (os.environ.get("NEO4J_USER") or os.environ.get("GRAPH_NEO4J_USER") or "neo4j").strip()
        password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GRAPH_NEO4J_PASSWORD") or ""
        try:
            drv = AsyncGraphDatabase.driver(uri, auth=(user, password))
        except Exception:
            logger.exception("rule_engine_neo4j_driver_init_failed")
            return None
        return cls(drv)

    async def close(self) -> None:
        await self._driver.close()

    async def fetch_graph_context(self, transaction: TransactionSchema) -> dict[str, Any]:
        meta = transaction.metadata or {}
        uid = _meta_str(meta, "user_id", "graph_user_id", "user")
        ip = _meta_str(meta, "ip", "ip_address", "graph_ip")
        if not uid or not ip:
            return {GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD: 0}

        q = """
        MATCH (u:User {user_id: $uid})-[:ORDERED_FROM_IP]->(ip:IP {address: $addr})
        MATCH (ip)<-[:ORDERED_FROM_IP]-(b:User)
        WHERE coalesce(b.is_blocked, false) = true AND b.user_id <> $uid
        RETURN count(DISTINCT b) AS n
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, uid=uid, addr=ip)
            rec = await result.single()
            if rec is None or rec.get("n") is None:
                return 0
            return int(rec["n"])

        async with self._driver.session() as session:
            n = await session.execute_read(work)
        return {GRAPH_LINKED_TO_BLOCKED_COUNT_FIELD: n}
