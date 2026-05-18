"""
Graph sidecar for the orchestrator: maps :class:`~ingestor.manifest_schema.TransactionSchema`
envelopes into a small entity–relationship graph.

**Backends**

* **Neo4j** (default when ``NEO4J_URI`` is set): Bolt driver, Cypher ``MERGE`` upserts.
* **JanusGraph** (``GRAPH_BACKEND=janusgraph`` + ``GREMLIN_REMOTE_URL``): Gremlin traversals
  via ``gremlinpython`` (optional install).

**Metadata → graph (inside ``transaction.metadata``)**

Canonical keys (first match wins per field):

* **User** ``user_id``: ``user_id``, ``graph_user_id``, ``user``
* **IP** ``address``: ``ip``, ``ip_address``, ``graph_ip``
* **Device** ``device_id``: ``device_id``, ``device_fingerprint``, ``graph_device_id``
* **Card** ``card_id``: ``card_id``, ``card_fingerprint``, ``graph_card_id``
* **Email** ``email``: ``email``, ``graph_email``
* **Address** ``line1``: ``address``, ``billing_address``, ``graph_address``
* **Order** ``order_id``: ``order_id``, ``graph_order_id`` (linked from ``User`` for knowledge-drop / dispute flows)
* **Passport** ``passport_id``: ``passport_id``, ``passport_number``, ``graph_passport_id``

**Edges (all carry ``transaction_id`` + ``observed_at``)**

* ``(User)-[:USED_DEVICE]->(Device)`` when ``user_id`` + ``device_id``
* ``(User)-[:ORDERED_FROM_IP]->(IP)`` when ``user_id`` + ``ip``
* ``(User)-[:PAID_WITH_CARD]->(Card)`` when ``user_id`` + ``card_id``
* ``(User)-[:PLACED_ORDER]->(Order)`` when ``user_id`` + ``order_id``
* ``(User)-[:IDENTIFIED_WITH_PASSPORT]->(Passport)`` when ``user_id`` + ``passport_id``
* ``(User)-[:LIVES_AT]->(Address)`` when ``user_id`` + physical/billing ``address`` (``line1``)

Gate (Neo4j): set ``NEO4J_TEST_URI`` / auth env vars and run ``pytest …/test_graph_client_gate.py``.

**Signals** — :meth:`GraphClient.get_graph_signals`:

* **User anchor** — ``entity_id`` is ``user_id``; IP anchor — ``ip:<address>`` (case-insensitive ``ip:`` prefix).
* **degree_centrality** — distinct neighbor nodes by label (undirected ``-[r]-`` from anchor).
* **two_hop_distinct_cards_last_2h** — for a **User**, cards via ``User→IP←User→Card`` with both edges ``observed_at`` in the last 2h; for an **IP**, ``IP←User→Card`` in the last 2h.
* **clustering** — device-sharing neighborhood: Watts–Strogatz–style local coefficient on users who share a device with the anchor, plus count of other accounts that share the anchor's first **three** devices (when the anchor has at least three).
* **IP_VELOCITY** — for **IP**, distinct users on that IP in the last 2h; for **User**, peak of that count over the user's IPs. ``spike`` when count exceeds :data:`IP_VELOCITY_SYBIL_THRESHOLD` (default **5**).
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from ingestor.manifest_schema import TransactionSchema

logger = logging.getLogger(__name__)

# --- Structural velocity / Sybil heuristics (tunable per deployment) ---

IP_VELOCITY_SYBIL_THRESHOLD = 5
"""Distinct ``User`` nodes on one ``IP`` within the velocity window above this ⇒ ``IP_VELOCITY.spike``."""

GRAPH_SIGNALS_IP_VELOCITY_WINDOW = timedelta(hours=2)
"""Horizon for IP↔user velocity and 2-hop card counts."""

GRAPH_SIGNALS_TWO_HOP_CARD_WINDOW = timedelta(hours=2)

CLUSTERING_MIN_DEVICES = 3
"""Minimum shared devices required for the ``accounts_sharing_three_devices`` metric."""

_GRAPH_ENTITY_IP = re.compile(r"(?i)^ip:(.+)$")


def _neighbor_max_hops_from_env() -> int:
    """
    Neighbor expansion depth for orchestrator graph probes — from validated deployment settings
    (``GRAPH_MAX_HOPS`` / ``TARKA_DEPLOY_PROFILE``) with a safe fallback when the shared settings
    package is unavailable.
    """
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().graph_neighbor_max_hops
    except Exception:
        raw = (os.environ.get("GRAPH_MAX_HOPS") or "").strip()
        if raw.isdigit():
            v = int(raw)
            return max(1, min(v, 16))
        return 2


def _safe_graph_key(s: str) -> bool:
    return "\x00" not in s and 0 < len(s) <= 512

# --- Schema constants (labels / rel types are fixed; never interpolated from user metadata) ---

LABEL_USER = "User"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
LABEL_CARD = "Card"
LABEL_EMAIL = "Email"
LABEL_ADDRESS = "Address"
LABEL_ORDER = "Order"
LABEL_PASSPORT = "Passport"
LABEL_LISTING = "Listing"

REL_USED_DEVICE = "USED_DEVICE"
REL_ORDERED_FROM_IP = "ORDERED_FROM_IP"
REL_PAID_WITH_CARD = "PAID_WITH_CARD"
REL_PLACED_ORDER = "PLACED_ORDER"
REL_IDENTIFIED_WITH_PASSPORT = "IDENTIFIED_WITH_PASSPORT"
REL_LIVES_AT = "LIVES_AT"
REL_REVIEWED = "REVIEWED"


@dataclass(frozen=True, slots=True)
class GraphHints:
    """Resolved string identities extracted from a transaction envelope."""

    user_id: str | None
    device_id: str | None
    ip: str | None
    card_id: str | None
    email: str | None
    address: str | None
    order_id: str | None
    passport_id: str | None
    listing_id: str | None
    user_marked_blocked: bool

    def any(self) -> bool:
        return any(
            (
                self.user_id,
                self.device_id,
                self.ip,
                self.card_id,
                self.email,
                self.address,
                self.order_id,
                self.passport_id,
                self.listing_id,
            ),
        )


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


def parse_graph_entity_ref(entity_id: str) -> tuple[Literal["user", "ip"], str]:
    """
    Interpret ``entity_id`` for :meth:`GraphClient.get_graph_signals`.

    * ``ip:<address>`` — anchor is an :class:`IP` node (``<address>`` must match stored ``address``).
    * Any other non-empty string — anchor is a :class:`User` ``user_id``.
    """
    raw = (entity_id or "").strip()
    if not raw:
        raise ValueError("entity_id must be non-empty")
    m = _GRAPH_ENTITY_IP.match(raw)
    if m:
        tail = m.group(1).strip()
        if not _safe_graph_key(tail):
            raise ValueError("invalid ip: entity reference")
        return "ip", tail
    if not _safe_graph_key(raw):
        raise ValueError("invalid user entity_id")
    return "user", raw


def ip_velocity_block(*, distinct_users_last_2h: int, threshold: int = IP_VELOCITY_SYBIL_THRESHOLD) -> dict[str, Any]:
    """Pure scoring for ``IP_VELOCITY`` (used by tests and Neo4j implementation)."""
    spike = distinct_users_last_2h > threshold
    denom = max(float(threshold), 1.0)
    score = min(float(distinct_users_last_2h) / denom, 10.0)
    return {
        "distinct_users_last_2h": distinct_users_last_2h,
        "threshold": threshold,
        "spike": spike,
        "score": score,
    }


def graph_hints_from_transaction(transaction: TransactionSchema) -> GraphHints:
    """Map ``TransactionSchema`` (+ ``metadata``) into graph upsert hints."""
    meta = transaction.metadata or {}
    blocked_raw = meta.get("graph_user_is_blocked")
    user_marked_blocked = blocked_raw is True or str(blocked_raw).strip().lower() in ("true", "1", "yes")
    return GraphHints(
        user_id=_meta_str(meta, "user_id", "graph_user_id", "user"),
        device_id=_meta_str(meta, "device_id", "device_fingerprint", "graph_device_id"),
        ip=_meta_str(meta, "ip", "ip_address", "graph_ip"),
        card_id=_meta_str(meta, "card_id", "card_fingerprint", "graph_card_id"),
        email=_meta_str(meta, "email", "graph_email"),
        address=_meta_str(meta, "address", "billing_address", "graph_address"),
        order_id=_meta_str(meta, "order_id", "graph_order_id"),
        passport_id=_meta_str(meta, "passport_id", "passport_number", "graph_passport_id"),
        listing_id=_meta_str(meta, "listing_id", "review_listing_id", "marketplace_listing_id"),
        user_marked_blocked=user_marked_blocked,
    )


class GraphClient(ABC):
    """Upsert graph entities for each ingest; optional read helpers for gates / dashboards."""

    @abstractmethod
    async def ingest_transaction(self, transaction: TransactionSchema) -> None:
        """Upsert nodes and relationship rows for this transaction (idempotent on ``transaction_id``)."""

    @abstractmethod
    async def users_connected_to_ip(self, ip: str) -> list[str]:
        """Return distinct ``user_id`` values linked to ``ip`` via ``ORDERED_FROM_IP``."""

    @abstractmethod
    async def get_graph_signals(self, entity_id: str) -> dict[str, Any]:
        """
        Structural velocity + clustering metrics for a **User** (``user_id``) or **IP** (``ip:<address>``).

        Returned keys are stable JSON-friendly dicts (counts, floats, bools).
        """

    @abstractmethod
    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Hardware reuse risk: whether ``device_id`` was used by a **blocked** :class:`User` node.

        ``current_user_id`` (optional) excludes that account from the blocked-neighbor set so a
        self-match does not suppress cross-account linkage on shared devices.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release driver / Gremlin resources."""

    async def knowledge_linked_users(self, detected_id: str) -> dict[str, Any]:
        """
        Resolve a **detected** analyst token against the fraud graph.

        Returns JSON-friendly keys: ``found``, ``match_kind``, ``linked_user_ids``,
        ``related_entity_ids`` (transaction ``entity_id`` strings when present on edges).
        """
        _ = detected_id
        return {
            "found": False,
            "match_kind": None,
            "linked_user_ids": [],
            "related_entity_ids": [],
            "backend": "none",
        }

    async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, Any]:
        """Default: no graph backend."""
        uid = (anchor_user_id or "").strip()
        empty: dict[str, Any] = {
            "found": False,
            "anchor_user_id": uid,
            "network_user_ids": [],
            "network_transaction_ids": [],
            "network_device_ids": [],
            "network_ip_addresses": [],
            "blocked_device_touch_count": 0,
            "neighbor_node_count": 0,
            "edges_summary": [],
            "backend": "none",
        }
        if not uid or not _safe_graph_key(uid):
            return empty
        return empty


class NullGraphClient(GraphClient):
    """No-op client when graph is disabled or not configured."""

    async def ingest_transaction(self, transaction: TransactionSchema) -> None:
        return None

    async def users_connected_to_ip(self, ip: str) -> list[str]:
        return []

    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, Any]:
        _ = current_user_id
        return {
            "device_id": device_id,
            "linked_to_blocked_node": False,
            "blocked_user_count_on_device": 0,
        }

    async def get_graph_signals(self, entity_id: str) -> dict[str, Any]:
        anchor, _ = parse_graph_entity_ref(entity_id)
        return {
            "entity_ref": entity_id.strip(),
            "anchor": anchor,
            "degree_centrality": {"total_distinct_neighbors": 0, "by_neighbor_label": {}},
            "two_hop_distinct_cards_last_2h": 0,
            "clustering": {
                "coefficient": 0.0,
                "accounts_sharing_three_devices": 0,
                "neighbor_user_count": 0,
            },
            "IP_VELOCITY": ip_velocity_block(distinct_users_last_2h=0),
            "backend": "none",
        }

    async def close(self) -> None:
        return None


class Neo4jGraphClient(GraphClient):
    """Neo4j Bolt: ``MERGE`` nodes; relationship identity includes ``transaction_id`` for idempotency."""

    def __init__(self, driver: Any, *, neighbor_max_hops: int | None = None) -> None:
        self._driver = driver
        self._neighbor_max_hops = (
            int(neighbor_max_hops) if neighbor_max_hops is not None else _neighbor_max_hops_from_env()
        )

    @classmethod
    def try_from_env(cls) -> Neo4jGraphClient | None:
        from neo4j import AsyncGraphDatabase

        uri = (os.environ.get("NEO4J_URI") or os.environ.get("GRAPH_NEO4J_URI") or "").strip()
        if not uri:
            return None
        user = (os.environ.get("NEO4J_USER") or os.environ.get("GRAPH_NEO4J_USER") or "neo4j").strip()
        password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GRAPH_NEO4J_PASSWORD") or ""
        try:
            drv = AsyncGraphDatabase.driver(uri, auth=(user, password))
        except Exception:
            logger.exception("neo4j_driver_init_failed uri=%s", uri.split("@")[-1])
            return None
        return cls(drv)

    async def close(self) -> None:
        await self._driver.close()

    async def ingest_transaction(self, transaction: TransactionSchema) -> None:
        hints = graph_hints_from_transaction(transaction)
        if not hints.any() and hints.user_id is None:
            return
        tid = str(transaction.entity_id)
        ts: datetime = transaction.timestamp

        async def work(tx: Any) -> None:
            if hints.user_id:
                await tx.run(
                    f"""
                    MERGE (u:`{LABEL_USER}` {{user_id: $user_id}})
                    SET u.is_blocked = coalesce(u.is_blocked, false) OR $blocked
                    """,
                    user_id=hints.user_id,
                    blocked=hints.user_marked_blocked,
                )
            if hints.device_id:
                await tx.run(
                    f"""
                    MERGE (d:`{LABEL_DEVICE}` {{device_id: $device_id}})
                    """,
                    device_id=hints.device_id,
                )
            if hints.ip:
                await tx.run(
                    f"""
                    MERGE (ip:`{LABEL_IP}` {{address: $address}})
                    """,
                    address=hints.ip,
                )
            if hints.card_id:
                await tx.run(
                    f"""
                    MERGE (c:`{LABEL_CARD}` {{card_id: $card_id}})
                    """,
                    card_id=hints.card_id,
                )
            if hints.email:
                await tx.run(
                    f"""
                    MERGE (e:`{LABEL_EMAIL}` {{email: $email}})
                    """,
                    email=hints.email,
                )
            if hints.address:
                await tx.run(
                    f"""
                    MERGE (a:`{LABEL_ADDRESS}` {{line1: $line1}})
                    """,
                    line1=hints.address,
                )

            if hints.user_id and hints.device_id:
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (d:`{LABEL_DEVICE}` {{device_id: $device_id}})
                    MERGE (u)-[r:`{REL_USED_DEVICE}` {{transaction_id: $tid}}]->(d)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    device_id=hints.device_id,
                    tid=tid,
                    ts=ts,
                )
            if hints.user_id and hints.ip:
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (ip:`{LABEL_IP}` {{address: $address}})
                    MERGE (u)-[r:`{REL_ORDERED_FROM_IP}` {{transaction_id: $tid}}]->(ip)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    address=hints.ip,
                    tid=tid,
                    ts=ts,
                )
            if hints.user_id and hints.card_id:
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (c:`{LABEL_CARD}` {{card_id: $card_id}})
                    MERGE (u)-[r:`{REL_PAID_WITH_CARD}` {{transaction_id: $tid}}]->(c)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    card_id=hints.card_id,
                    tid=tid,
                    ts=ts,
                )
            if hints.user_id and hints.address:
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (a:`{LABEL_ADDRESS}` {{line1: $line1}})
                    MERGE (u)-[r:`{REL_LIVES_AT}` {{transaction_id: $tid}}]->(a)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    line1=hints.address,
                    tid=tid,
                    ts=ts,
                )
            if hints.user_id and hints.order_id:
                await tx.run(
                    f"""
                    MERGE (o:`{LABEL_ORDER}` {{order_id: $order_id}})
                    """,
                    order_id=hints.order_id,
                )
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (o:`{LABEL_ORDER}` {{order_id: $order_id}})
                    MERGE (u)-[r:`{REL_PLACED_ORDER}` {{transaction_id: $tid}}]->(o)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    order_id=hints.order_id,
                    tid=tid,
                    ts=ts,
                )
            if hints.user_id and hints.passport_id:
                await tx.run(
                    f"""
                    MERGE (p:`{LABEL_PASSPORT}` {{passport_id: $passport_id}})
                    """,
                    passport_id=hints.passport_id,
                )
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (p:`{LABEL_PASSPORT}` {{passport_id: $passport_id}})
                    MERGE (u)-[r:`{REL_IDENTIFIED_WITH_PASSPORT}` {{transaction_id: $tid}}]->(p)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    passport_id=hints.passport_id,
                    tid=tid,
                    ts=ts,
                )
            if hints.listing_id:
                await tx.run(
                    f"""
                    MERGE (lst:`{LABEL_LISTING}` {{listing_id: $lid}})
                    """,
                    lid=hints.listing_id,
                )
            if hints.user_id and hints.listing_id:
                await tx.run(
                    f"""
                    MATCH (u:`{LABEL_USER}` {{user_id: $user_id}})
                    MATCH (lst:`{LABEL_LISTING}` {{listing_id: $lid}})
                    MERGE (u)-[r:`{REL_REVIEWED}` {{transaction_id: $tid}}]->(lst)
                    SET r.observed_at = $ts
                    """,
                    user_id=hints.user_id,
                    lid=hints.listing_id,
                    tid=tid,
                    ts=ts,
                )

        async with self._driver.session() as session:
            await session.execute_write(work)

    async def users_connected_to_ip(self, ip: str) -> list[str]:
        q = f"""
        MATCH (ip:`{LABEL_IP}` {{address: $address}})<-[:`{REL_ORDERED_FROM_IP}`]-(u:`{LABEL_USER}`)
        RETURN DISTINCT u.user_id AS user_id
        ORDER BY user_id
        """

        async def work(tx: Any) -> list[str]:
            result = await tx.run(q, address=ip)
            out: list[str] = []
            async for record in result:
                uid = record.get("user_id")
                if uid is not None:
                    out.append(str(uid))
            return out

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def get_graph_signals(self, entity_id: str) -> dict[str, Any]:
        anchor, ref = parse_graph_entity_ref(entity_id)
        now = datetime.now(UTC)
        cutoff = now - GRAPH_SIGNALS_IP_VELOCITY_WINDOW
        cutoff_cards = now - GRAPH_SIGNALS_TWO_HOP_CARD_WINDOW

        if anchor == "ip":
            by_lbl, total_deg = await self._degree_neighbors(LABEL_IP, "address", ref)
            distinct_ip_users = await self._distinct_users_on_ip_since(ref, cutoff)
            two_hop_cards = await self._two_hop_cards_from_ip_since(ref, cutoff_cards)
            cluster_block = {
                "coefficient": 0.0,
                "accounts_sharing_three_devices": 0,
                "neighbor_user_count": 0,
            }
            ip_vel = ip_velocity_block(distinct_users_last_2h=distinct_ip_users)
        else:
            by_lbl, total_deg = await self._degree_neighbors(LABEL_USER, "user_id", ref)
            two_hop_cards = await self._two_hop_cards_for_user_since(ref, cutoff_cards)
            cluster_block = await self._clustering_metrics_user(ref)
            peak_on_user_ips = await self._peak_distinct_users_on_anchor_user_ips(ref, cutoff)
            ip_vel = ip_velocity_block(distinct_users_last_2h=peak_on_user_ips)

        return {
            "entity_ref": entity_id.strip(),
            "anchor": anchor,
            "degree_centrality": {
                "total_distinct_neighbors": total_deg,
                "by_neighbor_label": by_lbl,
            },
            "two_hop_distinct_cards_last_2h": two_hop_cards,
            "clustering": cluster_block,
            "IP_VELOCITY": ip_vel,
            "backend": "neo4j",
        }

    async def _degree_neighbors(self, label: str, key: str, value: str) -> tuple[dict[str, int], int]:
        q = f"""
        MATCH (x:`{label}` {{{key}: $id}})-[r]-(n)
        RETURN head(labels(n)) AS lbl, count(DISTINCT n) AS cnt
        """

        async def work(tx: Any) -> tuple[dict[str, int], int]:
            result = await tx.run(q, id=value)
            by: dict[str, int] = {}
            total = 0
            async for rec in result:
                lbl = rec.get("lbl")
                c = rec.get("cnt")
                if lbl is None or c is None:
                    continue
                by[str(lbl)] = int(c)
                total += int(c)
            return by, total

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def _distinct_users_on_ip_since(self, ip_address: str, cutoff: datetime) -> int:
        q = f"""
        MATCH (ip:`{LABEL_IP}` {{address: $addr}})<-[r:`{REL_ORDERED_FROM_IP}`]-(u:`{LABEL_USER}`)
        WHERE r.observed_at >= $cutoff
        RETURN count(DISTINCT u) AS k
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, addr=ip_address, cutoff=cutoff)
            rec = await result.single()
            return int(rec["k"]) if rec and rec.get("k") is not None else 0

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def _peak_distinct_users_on_anchor_user_ips(self, user_id: str, cutoff: datetime) -> int:
        q = f"""
        MATCH (anchor:`{LABEL_USER}` {{user_id: $uid}})-[:`{REL_ORDERED_FROM_IP}`]->(ip:`{LABEL_IP}`)
        WITH DISTINCT ip
        MATCH (ip)<-[r:`{REL_ORDERED_FROM_IP}`]-(x:`{LABEL_USER}`)
        WHERE r.observed_at >= $cutoff
        WITH ip, count(DISTINCT x) AS c
        RETURN coalesce(max(c), 0) AS peak
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, uid=user_id, cutoff=cutoff)
            rec = await result.single()
            return int(rec["peak"]) if rec and rec.get("peak") is not None else 0

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def _two_hop_cards_for_user_since(self, user_id: str, cutoff: datetime) -> int:
        q = f"""
        MATCH (anchor:`{LABEL_USER}` {{user_id: $uid}})-[:`{REL_ORDERED_FROM_IP}`]->(ip:`{LABEL_IP}`)
        MATCH (ip)<-[r1:`{REL_ORDERED_FROM_IP}`]-(other:`{LABEL_USER}`)-[r2:`{REL_PAID_WITH_CARD}`]->(c:`{LABEL_CARD}`)
        WHERE r1.observed_at >= $cutoff AND r2.observed_at >= $cutoff
        RETURN count(DISTINCT c) AS n
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, uid=user_id, cutoff=cutoff)
            rec = await result.single()
            return int(rec["n"]) if rec and rec.get("n") is not None else 0

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def _two_hop_cards_from_ip_since(self, ip_address: str, cutoff: datetime) -> int:
        q = f"""
        MATCH (ip:`{LABEL_IP}` {{address: $addr}})<-[r1:`{REL_ORDERED_FROM_IP}`]-(u:`{LABEL_USER}`)-[r2:`{REL_PAID_WITH_CARD}`]->(c:`{LABEL_CARD}`)
        WHERE r1.observed_at >= $cutoff AND r2.observed_at >= $cutoff
        RETURN count(DISTINCT c) AS n
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, addr=ip_address, cutoff=cutoff)
            rec = await result.single()
            return int(rec["n"]) if rec and rec.get("n") is not None else 0

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def _clustering_metrics_user(self, user_id: str) -> dict[str, Any]:
        q_neighbors = f"""
        MATCH (anchor:`{LABEL_USER}` {{user_id: $uid}})-[:`{REL_USED_DEVICE}`]->(d:`{LABEL_DEVICE}`)
        <-[:`{REL_USED_DEVICE}`]-(v:`{LABEL_USER}`)
        WHERE v <> anchor
        RETURN count(DISTINCT v) AS k
        """
        km = CLUSTERING_MIN_DEVICES
        q_share_three = f"""
        MATCH (anchor:`{LABEL_USER}` {{user_id: $uid}})-[:`{REL_USED_DEVICE}`]->(d:`{LABEL_DEVICE}`)
        WITH anchor, collect(DISTINCT d) AS ds
        WHERE size(ds) >= {km}
        WITH anchor, ds[0..{km}] AS pick
        UNWIND pick AS p
        MATCH (p)<-[:`{REL_USED_DEVICE}`]-(o:`{LABEL_USER}`)
        WHERE o <> anchor
        WITH o, count(DISTINCT p) AS touched, size(pick) AS need
        WHERE touched = need
        RETURN count(DISTINCT o) AS n3
        """
        q_coeff = f"""
        MATCH (anchor:`{LABEL_USER}` {{user_id: $uid}})-[:`{REL_USED_DEVICE}`]->(d:`{LABEL_DEVICE}`)
        <-[:`{REL_USED_DEVICE}`]-(v:`{LABEL_USER}`)
        WHERE v <> anchor
        WITH collect(DISTINCT v) AS neigh
        WITH neigh, size(neigh) AS k
        WHERE k >= 2
        UNWIND neigh AS a
        UNWIND neigh AS b
        WHERE elementId(a) < elementId(b)
        OPTIONAL MATCH (a)-[:`{REL_USED_DEVICE}`]->(dd:`{LABEL_DEVICE}`)<-[:`{REL_USED_DEVICE}`]-(b)
        WITH k, a, b, count(DISTINCT dd) AS shared
        WHERE shared >= 1
        RETURN k, count(*) AS connected_pairs
        """

        async def work(tx: Any) -> dict[str, Any]:
            r0 = await tx.run(q_neighbors, uid=user_id)
            rec0 = await r0.single()
            k = int(rec0["k"]) if rec0 and rec0.get("k") is not None else 0

            r1 = await tx.run(q_share_three, uid=user_id)
            rec1 = await r1.single()
            n3 = int(rec1["n3"]) if rec1 and rec1.get("n3") is not None else 0

            coeff = 0.0
            if k >= 2:
                r2 = await tx.run(q_coeff, uid=user_id)
                rec2 = await r2.single()
                if rec2 and rec2.get("connected_pairs") is not None and rec2.get("k") is not None:
                    kk = int(rec2["k"])
                    pairs = int(rec2["connected_pairs"])
                    denom = kk * (kk - 1)
                    if denom > 0:
                        coeff = min(1.0, (2.0 * pairs) / float(denom))

            return {
                "coefficient": coeff,
                "accounts_sharing_three_devices": n3,
                "neighbor_user_count": k,
            }

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, Any]:
        q = f"""
        MATCH (d:`{LABEL_DEVICE}` {{device_id: $did}})<-[:`{REL_USED_DEVICE}`]-(u:`{LABEL_USER}`)
        WHERE coalesce(u.is_blocked, false) = true
          AND ($current_uid IS NULL OR u.user_id <> $current_uid)
        RETURN count(DISTINCT u) AS n
        """

        async def work(tx: Any) -> int:
            result = await tx.run(q, did=device_id, current_uid=current_user_id)
            rec = await result.single()
            return int(rec["n"]) if rec and rec.get("n") is not None else 0

        async with self._driver.session() as session:
            n = await session.execute_read(work)
        return {
            "device_id": device_id,
            "linked_to_blocked_node": n >= 1,
            "blocked_user_count_on_device": n,
        }

    async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, Any]:
        """Undirected ≤N-hop neighborhood (``GRAPH_MAX_HOPS``) around ``User {user_id}`` for cluster context."""
        uid = (anchor_user_id or "").strip()
        empty: dict[str, Any] = {
            "found": False,
            "anchor_user_id": uid,
            "network_user_ids": [],
            "network_transaction_ids": [],
            "network_device_ids": [],
            "network_ip_addresses": [],
            "blocked_device_touch_count": 0,
            "neighbor_node_count": 0,
            "edges_summary": [],
            "backend": "neo4j",
        }
        if not uid or not _safe_graph_key(uid):
            return empty

        nh = max(1, min(self._neighbor_max_hops, 16))
        q_exist = f"MATCH (a:`{LABEL_USER}` {{user_id: $uid}}) RETURN count(a) AS c"
        q_neighbors = f"""
        MATCH (a:`{LABEL_USER}` {{user_id: $uid}})-[rs*1..{nh}]-(node)
        WHERE elementId(node) <> elementId(a)
        UNWIND rs AS r
        RETURN type(r) AS rel_type, labels(node)[0] AS nlabel, node AS node, r.transaction_id AS tid
        """
        q_blocked_devices = f"""
        MATCH (a:`{LABEL_USER}` {{user_id: $uid}})-[*1..{nh}]-(d:`{LABEL_DEVICE}`)
        MATCH (d)<-[:`{REL_USED_DEVICE}`]-(u:`{LABEL_USER}`)
        WHERE coalesce(u.is_blocked, false) = true
        RETURN count(DISTINCT d) AS bc
        """

        async def work(tx: Any) -> dict[str, Any]:
            chk = await (await tx.run(q_exist, uid=uid)).single()
            if not chk or int(chk.get("c") or 0) == 0:
                return empty

            users: set[str] = {uid}
            devices: set[str] = set()
            ips: set[str] = set()
            txids: set[str] = set()
            edges: list[dict[str, str]] = []

            async def consume(result: Any) -> None:
                async for row in result:
                    tid_raw = row.get("tid")
                    if tid_raw is not None:
                        ts = str(tid_raw).strip()
                        if ts and ts.lower() not in ("none", "null"):
                            txids.add(ts)
                    node = row.get("node")
                    if node is None:
                        continue
                    rel_type = str(row.get("rel_type") or "REL")
                    nlabel = str(row.get("nlabel") or "")
                    try:
                        labels = list(node.labels)
                    except Exception:
                        labels = [nlabel]
                    pl = labels[0] if labels else nlabel
                    if pl == LABEL_USER:
                        try:
                            uu = node["user_id"]
                        except KeyError:
                            uu = None
                        if uu is not None and str(uu).strip():
                            users.add(str(uu).strip())
                    elif pl == LABEL_DEVICE:
                        try:
                            dd = node["device_id"]
                        except KeyError:
                            dd = None
                        if dd is not None and str(dd).strip():
                            devices.add(str(dd).strip())
                    elif pl == LABEL_IP:
                        try:
                            addr = node["address"]
                        except KeyError:
                            addr = None
                        if addr is not None and str(addr).strip():
                            ips.add(str(addr).strip())
                    preview = ""
                    for key in ("user_id", "device_id", "address", "card_id", "line1"):
                        try:
                            v = node[key]
                        except KeyError:
                            v = None
                        if v is not None and str(v).strip():
                            preview = str(v).strip()[:64]
                            break
                    edges.append({"rel": rel_type, "end_label": pl, "preview": preview})

            await consume(await tx.run(q_neighbors, uid=uid))

            brec = await (await tx.run(q_blocked_devices, uid=uid)).single()
            blocked_d = int(brec.get("bc") or 0) if brec else 0

            return {
                "found": True,
                "anchor_user_id": uid,
                "network_user_ids": sorted(users),
                "network_transaction_ids": sorted(txids),
                "network_device_ids": sorted(devices),
                "network_ip_addresses": sorted(ips),
                "blocked_device_touch_count": blocked_d,
                "neighbor_node_count": len(users) + len(devices) + len(ips),
                "edges_summary": edges[:80],
                "backend": "neo4j",
            }

        async with self._driver.session() as session:
            return await session.execute_read(work)

    async def knowledge_linked_users(self, detected_id: str) -> dict[str, Any]:
        from uuid import UUID

        did = (detected_id or "").strip()
        if not did or not _safe_graph_key(did):
            return {
                "found": False,
                "match_kind": None,
                "linked_user_ids": [],
                "related_entity_ids": [],
                "backend": "neo4j",
            }

        q_txn = f"""
        MATCH (u:`{LABEL_USER}`)-[r]-()
        WHERE r.transaction_id = $tid
        RETURN collect(DISTINCT u.user_id) AS uids, collect(DISTINCT r.transaction_id) AS tids
        """
        q_order = f"""
        MATCH (o:`{LABEL_ORDER}` {{order_id: $oid}})<-[r:`{REL_PLACED_ORDER}`]-(u:`{LABEL_USER}`)
        RETURN collect(DISTINCT u.user_id) AS uids, collect(DISTINCT r.transaction_id) AS tids
        """
        q_passport = f"""
        MATCH (p:`{LABEL_PASSPORT}` {{passport_id: $pid}})
              <-[r:`{REL_IDENTIFIED_WITH_PASSPORT}`]-(u:`{LABEL_USER}`)
        RETURN collect(DISTINCT u.user_id) AS uids, collect(DISTINCT r.transaction_id) AS tids
        """
        q_user = f"""
        MATCH (u:`{LABEL_USER}` {{user_id: $uid}})
        RETURN collect(DISTINCT u.user_id) AS uids, [] AS tids
        """

        async def work(tx: Any) -> dict[str, Any]:
            uids: set[str] = set()
            tids: set[str] = set()
            kinds_hit: list[str] = []

            async def pull(kind: str, q: str, **params: Any) -> None:
                result = await tx.run(q, **params)
                rec = await result.single()
                if rec is None:
                    return
                raw_u = rec.get("uids")
                raw_t = rec.get("tids")
                u_list = [str(u) for u in (raw_u or []) if u is not None and str(u).strip()]
                t_list = [str(t) for t in (raw_t or []) if t is not None and str(t).strip()]
                if u_list or t_list:
                    kinds_hit.append(kind)
                uids.update(u_list)
                tids.update(t_list)

            try:
                UUID(did)
            except ValueError:
                pass
            else:
                await pull("transaction", q_txn, tid=did)

            await pull("order", q_order, oid=did)
            await pull("passport", q_passport, pid=did)
            await pull("user", q_user, uid=did)

            match_kind: str | None
            if not kinds_hit:
                match_kind = None
            elif len(kinds_hit) == 1:
                match_kind = kinds_hit[0]
            else:
                match_kind = "+".join(dict.fromkeys(kinds_hit))

            return {
                "found": bool(uids or tids),
                "match_kind": match_kind,
                "linked_user_ids": sorted(uids),
                "related_entity_ids": sorted(tids),
                "backend": "neo4j",
            }

        async with self._driver.session() as session:
            return await session.execute_read(work)


class JanusGraphClient(GraphClient):
    """
    JanusGraph via a remote Gremlin traversal (TinkerPop).

    Env: ``GREMLIN_REMOTE_URL`` (default ``ws://127.0.0.1:8182/gremlin``), ``GREMLIN_TRAVERSAL_SOURCE`` (``g``).
    """

    def __init__(self, g: Any, connection: Any, *, neighbor_max_hops: int | None = None) -> None:
        self._g = g
        self._connection = connection
        self._neighbor_max_hops = (
            int(neighbor_max_hops) if neighbor_max_hops is not None else _neighbor_max_hops_from_env()
        )

    @classmethod
    def try_from_env(cls) -> JanusGraphClient | None:
        try:
            from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
            from gremlin_python.structure.graph import Graph
        except ImportError:
            logger.warning("janusgraph_backend_selected_but_gremlinpython_missing")
            return None

        url = (os.environ.get("GREMLIN_REMOTE_URL") or "ws://127.0.0.1:8182/gremlin").strip()
        source = (os.environ.get("GREMLIN_TRAVERSAL_SOURCE") or "g").strip() or "g"
        try:
            conn = DriverRemoteConnection(url, source)
            g = Graph().traversal().withRemote(conn)
        except Exception:
            logger.exception("janus_gremlin_connect_failed url=%s", url)
            return None
        return cls(g, conn)

    async def close(self) -> None:
        try:
            self._connection.close()
        except Exception:
            logger.debug("janus_gremlin_close_failed", exc_info=True)

    def _two_hop_neighbor_network_sync(self, anchor_user_id: str) -> dict[str, Any]:
        from gremlin_python.process.traversal import T

        uid = (anchor_user_id or "").strip()
        out: dict[str, Any] = {
            "found": False,
            "anchor_user_id": uid,
            "network_user_ids": [],
            "network_transaction_ids": [],
            "network_device_ids": [],
            "network_ip_addresses": [],
            "blocked_device_touch_count": 0,
            "neighbor_node_count": 0,
            "edges_summary": [],
            "backend": "janusgraph",
        }
        if not uid or not _safe_graph_key(uid):
            return out
        g = self._g
        try:
            if g.V().has(LABEL_USER, "user_id", uid).limit(1).count().next() == 0:
                return out
        except Exception:
            logger.exception("janus_two_hop_anchor_probe_failed uid=%s", uid)
            return out
        users: set[str] = {uid}
        devices: set[str] = set()
        ips: set[str] = set()
        nh = max(1, min(self._neighbor_max_hops, 16))
        try:
            trav = g.V().has(LABEL_USER, "user_id", uid)
            for _ in range(nh):
                trav = trav.both().dedup()
            ems = trav.limit(400).elementMap().toList()
        except Exception:
            logger.exception("janus_two_hop_traversal_failed uid=%s", uid)
            out["found"] = True
            out["network_user_ids"] = sorted(users)
            out["network_ip_addresses"] = []
            return out
        for em in ems:
            lbl = em.get(T.label)
            if lbl == LABEL_USER and em.get("user_id") is not None:
                users.add(str(em["user_id"]))
            elif lbl == LABEL_DEVICE and em.get("device_id") is not None:
                devices.add(str(em["device_id"]))
            elif lbl == LABEL_IP and em.get("address") is not None:
                ips.add(str(em["address"]))
        out.update(
            {
                "found": True,
                "network_user_ids": sorted(users),
                "network_device_ids": sorted(devices),
                "network_ip_addresses": sorted(ips),
                "neighbor_node_count": len(users) + len(devices) + len(ips),
            },
        )
        return out

    async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, Any]:
        import asyncio

        return await asyncio.to_thread(self._two_hop_neighbor_network_sync, anchor_user_id)

    def _merge_vertex(self, label: str, key_prop: str, key_val: str) -> Any:
        from gremlin_python.process.graph_traversal import __

        return (
            self._g.V()
            .has(label, key_prop, key_val)
            .fold()
            .coalesce(__.unfold(), __.addV(label).property(key_prop, key_val))
            .next()
        )

    def _ingest_sync(self, transaction: TransactionSchema) -> None:
        from gremlin_python.process.graph_traversal import __

        hints = graph_hints_from_transaction(transaction)
        if not hints.any():
            return
        tid = str(transaction.entity_id)
        ts = transaction.timestamp.isoformat()
        g = self._g

        if hints.user_id:
            self._merge_vertex(LABEL_USER, "user_id", hints.user_id)
        if hints.device_id:
            self._merge_vertex(LABEL_DEVICE, "device_id", hints.device_id)
        if hints.ip:
            self._merge_vertex(LABEL_IP, "address", hints.ip)
        if hints.card_id:
            self._merge_vertex(LABEL_CARD, "card_id", hints.card_id)
        if hints.email:
            self._merge_vertex(LABEL_EMAIL, "email", hints.email)
        if hints.address:
            self._merge_vertex(LABEL_ADDRESS, "line1", hints.address)

        if hints.user_id and hints.device_id:
            u = g.V().has(LABEL_USER, "user_id", hints.user_id).next()
            d = g.V().has(LABEL_DEVICE, "device_id", hints.device_id).next()
            g.V(u).addE(REL_USED_DEVICE).to(__.V(d)).property("transaction_id", tid).property("observed_at", ts).iterate()

        if hints.user_id and hints.ip:
            u = g.V().has(LABEL_USER, "user_id", hints.user_id).next()
            ip_v = g.V().has(LABEL_IP, "address", hints.ip).next()
            g.V(u).addE(REL_ORDERED_FROM_IP).to(__.V(ip_v)).property("transaction_id", tid).property(
                "observed_at",
                ts,
            ).iterate()

        if hints.user_id and hints.card_id:
            u = g.V().has(LABEL_USER, "user_id", hints.user_id).next()
            c = g.V().has(LABEL_CARD, "card_id", hints.card_id).next()
            g.V(u).addE(REL_PAID_WITH_CARD).to(__.V(c)).property("transaction_id", tid).property(
                "observed_at",
                ts,
            ).iterate()

        if hints.user_id and hints.address:
            u = g.V().has(LABEL_USER, "user_id", hints.user_id).next()
            a = g.V().has(LABEL_ADDRESS, "line1", hints.address).next()
            g.V(u).addE(REL_LIVES_AT).to(__.V(a)).property("transaction_id", tid).property(
                "observed_at",
                ts,
            ).iterate()

        if hints.listing_id:
            self._merge_vertex(LABEL_LISTING, "listing_id", hints.listing_id)
        if hints.user_id and hints.listing_id:
            u = g.V().has(LABEL_USER, "user_id", hints.user_id).next()
            lst = g.V().has(LABEL_LISTING, "listing_id", hints.listing_id).next()
            g.V(u).addE(REL_REVIEWED).to(__.V(lst)).property("transaction_id", tid).property(
                "observed_at",
                ts,
            ).iterate()

    async def ingest_transaction(self, transaction: TransactionSchema) -> None:
        import asyncio

        await asyncio.to_thread(self._ingest_sync, transaction)

    def _users_for_ip_sync(self, ip: str) -> list[str]:
        raw = (
            self._g.V()
            .has(LABEL_IP, "address", ip)
            .in_(REL_ORDERED_FROM_IP)
            .hasLabel(LABEL_USER)
            .values("user_id")
            .dedup()
            .toList()
        )
        return sorted(str(x) for x in raw)

    async def users_connected_to_ip(self, ip: str) -> list[str]:
        import asyncio

        return await asyncio.to_thread(self._users_for_ip_sync, ip)

    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, Any]:
        _ = current_user_id
        return {
            "device_id": device_id,
            "linked_to_blocked_node": False,
            "blocked_user_count_on_device": 0,
        }

    async def get_graph_signals(self, entity_id: str) -> dict[str, Any]:
        anchor, _ = parse_graph_entity_ref(entity_id)
        return {
            "entity_ref": entity_id.strip(),
            "anchor": anchor,
            "degree_centrality": {"total_distinct_neighbors": 0, "by_neighbor_label": {}},
            "two_hop_distinct_cards_last_2h": 0,
            "clustering": {
                "coefficient": 0.0,
                "accounts_sharing_three_devices": 0,
                "neighbor_user_count": 0,
            },
            "IP_VELOCITY": ip_velocity_block(distinct_users_last_2h=0),
            "backend": "janusgraph",
            "signals_note": "get_graph_signals not yet implemented for Gremlin; use Neo4j backend.",
        }


def graph_client_from_environment() -> GraphClient:
    """Pick Neo4j, JanusGraph, or a no-op client from environment variables."""
    raw = os.environ.get("GRAPH_BACKEND")
    backend = "neo4j" if raw is None or not raw.strip() else raw.strip().lower()
    if backend in ("none", "off", "disabled"):
        return NullGraphClient()
    if backend == "janusgraph":
        jc = JanusGraphClient.try_from_env()
        return jc if jc is not None else NullGraphClient()
    neo = Neo4jGraphClient.try_from_env()
    return neo if neo is not None else NullGraphClient()
