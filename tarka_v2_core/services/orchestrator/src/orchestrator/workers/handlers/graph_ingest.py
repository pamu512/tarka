"""JanusGraph outbox handler: idempotent vertex/edge upserts for ``GRAPH_INGEST``."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ingestor.manifest_schema import TransactionSchema

from orchestrator.graph.client import (
    LABEL_ADDRESS,
    LABEL_CARD,
    LABEL_DEVICE,
    LABEL_EMAIL,
    LABEL_IP,
    LABEL_LISTING,
    LABEL_USER,
    REL_LIVES_AT,
    REL_ORDERED_FROM_IP,
    REL_PAID_WITH_CARD,
    REL_REVIEWED,
    REL_USED_DEVICE,
    GraphHints,
    JanusGraphClient,
    graph_hints_from_transaction,
)
from orchestrator.models.outbox import OUTBOX_EVENT_GRAPH_INGEST
from orchestrator.workers.handlers.base import BaseOutboxHandler

logger = logging.getLogger(__name__)

TARKA_AUDIT_LOG_ID_PROP = "tarka_audit_log_id"


class GraphDatabaseConnectionError(ConnectionError):
    """Raised when the JanusGraph Gremlin connection is unavailable or drops mid-flight."""


class GraphIngestPayloadError(ValueError):
    """Raised when a ``GRAPH_INGEST`` outbox payload is missing required fields."""


def _parse_audit_log_id(payload: dict[str, Any]) -> int:
    raw = payload.get("audit_log_id")
    if raw is None:
        raise GraphIngestPayloadError("audit_log_id is required in GRAPH_INGEST payload")
    try:
        audit_log_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise GraphIngestPayloadError(f"audit_log_id must be an integer, got {raw!r}") from exc
    if audit_log_id < 1:
        raise GraphIngestPayloadError("audit_log_id must be >= 1")
    return audit_log_id


def _parse_transaction(payload: dict[str, Any]) -> TransactionSchema:
    envelope = payload.get("edge_transaction_payload_envelope")
    if not isinstance(envelope, dict):
        raise GraphIngestPayloadError("edge_transaction_payload_envelope missing or not an object")
    return TransactionSchema.model_validate(envelope)


def _connect_janusgraph() -> JanusGraphClient:
    backend = (os.environ.get("GRAPH_BACKEND") or "").strip().lower()
    if backend not in ("", "janusgraph"):
        raise GraphDatabaseConnectionError(
            f"GRAPH_INGEST handler requires GRAPH_BACKEND=janusgraph (got {backend!r})",
        )
    client = JanusGraphClient.try_from_env()
    if client is None:
        raise GraphDatabaseConnectionError(
            "JanusGraph connection could not be established (check GREMLIN_REMOTE_URL and gremlinpython)",
        )
    return client


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True
    name = type(exc).__name__.lower()
    if "connection" in name or "closed" in name or "timeout" in name:
        return True
    msg = str(exc).lower()
    return "connection" in msg or "closed" in msg or "channel" in msg


def _run_gremlin(client: JanusGraphClient, op: str, fn: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        if _is_connection_error(exc):
            raise GraphDatabaseConnectionError(f"JanusGraph connection dropped during {op}") from exc
        raise


def _ensure_connection(client: JanusGraphClient) -> None:
    _run_gremlin(
        client,
        "connection_probe",
        lambda: client._g.inject(1).limit(1).toList(),
    )


def _read_int_property(client: JanusGraphClient, vertex: Any, prop: str) -> int | None:
    values = _run_gremlin(
        client,
        f"read_vertex_property_{prop}",
        lambda: client._g.V(vertex).values(prop).toList(),
    )
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def _vertex_matches_audit_log(
    client: JanusGraphClient,
    vertex: Any,
    audit_log_id: int,
) -> bool:
    existing = _read_int_property(client, vertex, TARKA_AUDIT_LOG_ID_PROP)
    return existing is not None and existing == audit_log_id


def _merge_vertex(
    client: JanusGraphClient,
    label: str,
    key_prop: str,
    key_val: str,
    *,
    audit_log_id: int,
) -> Any:
    from gremlin_python.process.graph_traversal import __

    g = client._g
    vertex = _run_gremlin(
        client,
        f"merge_vertex_{label}",
        lambda: g.V()
        .has(label, key_prop, key_val)
        .fold()
        .coalesce(__.unfold(), __.addV(label).property(key_prop, key_val))
        .next(),
    )
    if _vertex_matches_audit_log(client, vertex, audit_log_id):
        return vertex
    _run_gremlin(
        client,
        f"set_vertex_{TARKA_AUDIT_LOG_ID_PROP}",
        lambda: g.V(vertex).property(TARKA_AUDIT_LOG_ID_PROP, audit_log_id).iterate(),
    )
    return vertex


def _edge_matches_audit_log(
    client: JanusGraphClient,
    from_vertex: Any,
    rel_type: str,
    to_vertex: Any,
    *,
    transaction_id: str,
    audit_log_id: int,
) -> bool:
    from gremlin_python.process.graph_traversal import __

    g = client._g
    rows = _run_gremlin(
        client,
        f"find_edge_{rel_type}",
        lambda: g.V(from_vertex)
        .outE(rel_type)
        .where(__.inV().is_(to_vertex))
        .has("transaction_id", transaction_id)
        .values(TARKA_AUDIT_LOG_ID_PROP)
        .toList(),
    )
    if not rows:
        return False
    try:
        return int(rows[0]) == audit_log_id
    except (TypeError, ValueError):
        return False


def _upsert_edge(
    client: JanusGraphClient,
    from_vertex: Any,
    rel_type: str,
    to_vertex: Any,
    *,
    transaction_id: str,
    observed_at: str,
    audit_log_id: int,
) -> None:
    from gremlin_python.process.graph_traversal import __

    if _edge_matches_audit_log(
        client,
        from_vertex,
        rel_type,
        to_vertex,
        transaction_id=transaction_id,
        audit_log_id=audit_log_id,
    ):
        logger.debug(
            "graph_ingest_edge_idempotent_skip rel=%s transaction_id=%s audit_log_id=%s",
            rel_type,
            transaction_id,
            audit_log_id,
        )
        return

    g = client._g
    _run_gremlin(
        client,
        f"add_edge_{rel_type}",
        lambda: g.V(from_vertex)
        .addE(rel_type)
        .to(__.V(to_vertex))
        .property("transaction_id", transaction_id)
        .property("observed_at", observed_at)
        .property(TARKA_AUDIT_LOG_ID_PROP, audit_log_id)
        .iterate(),
    )


def _ingest_already_committed(
    client: JanusGraphClient,
    *,
    transaction_id: str,
    audit_log_id: int,
) -> bool:
    g = client._g
    count = _run_gremlin(
        client,
        "ingest_idempotency_probe",
        lambda: g.E()
        .has("transaction_id", transaction_id)
        .has(TARKA_AUDIT_LOG_ID_PROP, audit_log_id)
        .limit(1)
        .count()
        .next(),
    )
    return int(count) > 0


def _ingest_janus_sync(
    client: JanusGraphClient,
    transaction: TransactionSchema,
    *,
    audit_log_id: int,
) -> None:
    _ensure_connection(client)

    hints = graph_hints_from_transaction(transaction)
    if not hints.any() and hints.user_id is None:
        logger.info(
            "graph_ingest_noop entity_id=%s audit_log_id=%s reason=no_graph_hints",
            transaction.entity_id,
            audit_log_id,
        )
        return

    transaction_id = str(transaction.entity_id)
    if _ingest_already_committed(client, transaction_id=transaction_id, audit_log_id=audit_log_id):
        logger.info(
            "graph_ingest_idempotent_skip entity_id=%s audit_log_id=%s",
            transaction_id,
            audit_log_id,
        )
        return

    ts = transaction.timestamp.isoformat()
    _apply_janus_mutations(client, hints, transaction_id=transaction_id, observed_at=ts, audit_log_id=audit_log_id)


def _apply_janus_mutations(
    client: JanusGraphClient,
    hints: GraphHints,
    *,
    transaction_id: str,
    observed_at: str,
    audit_log_id: int,
) -> None:
    user_v = None
    if hints.user_id:
        user_v = _merge_vertex(client, LABEL_USER, "user_id", hints.user_id, audit_log_id=audit_log_id)
    if hints.device_id:
        _merge_vertex(client, LABEL_DEVICE, "device_id", hints.device_id, audit_log_id=audit_log_id)
    if hints.ip:
        _merge_vertex(client, LABEL_IP, "address", hints.ip, audit_log_id=audit_log_id)
    if hints.card_id:
        _merge_vertex(client, LABEL_CARD, "card_id", hints.card_id, audit_log_id=audit_log_id)
    if hints.email:
        _merge_vertex(client, LABEL_EMAIL, "email", hints.email, audit_log_id=audit_log_id)
    if hints.address:
        _merge_vertex(client, LABEL_ADDRESS, "line1", hints.address, audit_log_id=audit_log_id)

    g = client._g
    if hints.user_id and hints.device_id:
        u = user_v or _run_gremlin(
            client,
            "resolve_user_for_device_edge",
            lambda: g.V().has(LABEL_USER, "user_id", hints.user_id).next(),
        )
        d = _run_gremlin(
            client,
            "resolve_device_for_edge",
            lambda: g.V().has(LABEL_DEVICE, "device_id", hints.device_id).next(),
        )
        _upsert_edge(
            client,
            u,
            REL_USED_DEVICE,
            d,
            transaction_id=transaction_id,
            observed_at=observed_at,
            audit_log_id=audit_log_id,
        )

    if hints.user_id and hints.ip:
        u = user_v or _run_gremlin(
            client,
            "resolve_user_for_ip_edge",
            lambda: g.V().has(LABEL_USER, "user_id", hints.user_id).next(),
        )
        ip_v = _run_gremlin(
            client,
            "resolve_ip_for_edge",
            lambda: g.V().has(LABEL_IP, "address", hints.ip).next(),
        )
        _upsert_edge(
            client,
            u,
            REL_ORDERED_FROM_IP,
            ip_v,
            transaction_id=transaction_id,
            observed_at=observed_at,
            audit_log_id=audit_log_id,
        )

    if hints.user_id and hints.card_id:
        u = user_v or _run_gremlin(
            client,
            "resolve_user_for_card_edge",
            lambda: g.V().has(LABEL_USER, "user_id", hints.user_id).next(),
        )
        c = _run_gremlin(
            client,
            "resolve_card_for_edge",
            lambda: g.V().has(LABEL_CARD, "card_id", hints.card_id).next(),
        )
        _upsert_edge(
            client,
            u,
            REL_PAID_WITH_CARD,
            c,
            transaction_id=transaction_id,
            observed_at=observed_at,
            audit_log_id=audit_log_id,
        )

    if hints.user_id and hints.address:
        u = user_v or _run_gremlin(
            client,
            "resolve_user_for_address_edge",
            lambda: g.V().has(LABEL_USER, "user_id", hints.user_id).next(),
        )
        a = _run_gremlin(
            client,
            "resolve_address_for_edge",
            lambda: g.V().has(LABEL_ADDRESS, "line1", hints.address).next(),
        )
        _upsert_edge(
            client,
            u,
            REL_LIVES_AT,
            a,
            transaction_id=transaction_id,
            observed_at=observed_at,
            audit_log_id=audit_log_id,
        )

    if hints.listing_id:
        _merge_vertex(client, LABEL_LISTING, "listing_id", hints.listing_id, audit_log_id=audit_log_id)
    if hints.user_id and hints.listing_id:
        u = user_v or _run_gremlin(
            client,
            "resolve_user_for_listing_edge",
            lambda: g.V().has(LABEL_USER, "user_id", hints.user_id).next(),
        )
        lst = _run_gremlin(
            client,
            "resolve_listing_for_edge",
            lambda: g.V().has(LABEL_LISTING, "listing_id", hints.listing_id).next(),
        )
        _upsert_edge(
            client,
            u,
            REL_REVIEWED,
            lst,
            transaction_id=transaction_id,
            observed_at=observed_at,
            audit_log_id=audit_log_id,
        )


class GraphIngestHandler(BaseOutboxHandler):
    """Execute JanusGraph upserts for orchestrator ``GRAPH_INGEST`` outbox rows."""

    event_type = OUTBOX_EVENT_GRAPH_INGEST

    async def execute(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise GraphIngestPayloadError("graph ingest payload must be a dict")

        audit_log_id = _parse_audit_log_id(payload)
        transaction = _parse_transaction(payload)

        client = _connect_janusgraph()
        try:
            await asyncio.to_thread(
                _ingest_janus_sync,
                client,
                transaction,
                audit_log_id=audit_log_id,
            )
        except GraphDatabaseConnectionError:
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                raise GraphDatabaseConnectionError("JanusGraph connection dropped during GRAPH_INGEST") from exc
            raise
        finally:
            await client.close()

        logger.info(
            "graph_ingest_handler_completed entity_id=%s audit_log_id=%s",
            transaction.entity_id,
            audit_log_id,
        )
