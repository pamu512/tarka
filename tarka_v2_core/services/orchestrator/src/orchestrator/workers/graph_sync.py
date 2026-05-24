"""Graph backlink sync: lifecycle outcomes → JanusGraph vertex properties (Prompt 115)."""

from __future__ import annotations

import asyncio
import logging
from orchestrator.graph.client import GraphClient, JanusGraphClient, LABEL_USER, _safe_graph_key

logger = logging.getLogger(__name__)


def _mark_user_is_fraud_gremlin_sync(janus: JanusGraphClient, user_id: str) -> None:
    """Run Gremlin on the remote traversal source (blocking)."""
    uid = (user_id or "").strip()
    if not uid or not _safe_graph_key(uid):
        return
    from gremlin_python.process.traversal import Cardinality

    g = janus._g
    try:
        (
            g.V()
            .has(LABEL_USER, "user_id", uid)
            .property(Cardinality.single, "is_fraud", True)
            .iterate()
        )
    except Exception:
        logger.exception("janus_mark_user_is_fraud_failed user_id=%s", uid)


async def sync_resolved_fraud_case_to_graph(
    graph_client: GraphClient, *, user_link_key: str
) -> None:
    """
    When a lifecycle case is resolved as **fraud**, set ``is_fraud=true`` on the **User** vertex whose
    ``user_id`` matches ``user_link_key`` (the same key persisted on ``lifecycle_cases.user_link_key``
    from ingest metadata / entity fallback).

    Only **JanusGraph** (``JanusGraphClient``) is updated; other graph backends no-op here.
    """
    if not isinstance(graph_client, JanusGraphClient):
        return
    await asyncio.to_thread(_mark_user_is_fraud_gremlin_sync, graph_client, user_link_key)


def read_janus_user_is_fraud_values(janus: JanusGraphClient, user_id: str) -> list[object]:
    """
    Return Gremlin ``values('is_fraud')`` for the User anchor (empty list if missing / unset).

    Intended for manual gates and integration tests (Gremlin console equivalent:
    ``g.V().has('User','user_id','<id>').values('is_fraud')``).
    """
    uid = (user_id or "").strip()
    if not uid or not _safe_graph_key(uid):
        return []
    try:
        return janus._g.V().has(LABEL_USER, "user_id", uid).values("is_fraud").toList()
    except Exception:
        logger.exception("janus_read_is_fraud_failed user_id=%s", uid)
        return []
