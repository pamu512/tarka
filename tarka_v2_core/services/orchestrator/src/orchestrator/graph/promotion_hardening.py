"""JanusGraph hardening after hypothesis promotion (Prompt 200)."""

from __future__ import annotations

import logging
from typing import Any

from orchestrator.graph.client import GraphClient, LABEL_USER, _safe_graph_key

logger = logging.getLogger(__name__)


def _mark_user_high_risk_gremlin_sync(
    janus: Any,
    user_id: str,
    *,
    rule_id: str,
) -> bool:
    """Set ``high_risk=true`` on the User anchor (blocking Gremlin)."""
    uid = (user_id or "").strip()
    rid = (rule_id or "").strip()
    if not uid or not _safe_graph_key(uid):
        return False
    from gremlin_python.process.traversal import Cardinality

    g = janus._g
    try:
        trav = g.V().has(LABEL_USER, "user_id", uid)
        trav = trav.property(Cardinality.single, "high_risk", True)
        if rid:
            trav = trav.property(Cardinality.single, "high_risk_rule_id", rid)
        trav.iterate()
        return True
    except Exception:
        logger.exception("janus_mark_user_high_risk_failed user_id=%s rule_id=%s", uid, rid)
        return False


def read_janus_user_high_risk_values(janus: Any, user_id: str) -> list[object]:
    uid = (user_id or "").strip()
    if not uid or not _safe_graph_key(uid):
        return []
    try:
        return janus._g.V().has(LABEL_USER, "user_id", uid).values("high_risk").toList()
    except Exception:
        logger.exception("janus_read_high_risk_failed user_id=%s", uid)
        return []


async def apply_promotion_hardening_to_graph(
    graph_client: GraphClient | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Mark every entity in ``payload["entity_ids"]`` as ``high_risk`` on JanusGraph User vertices.
    """
    if graph_client is None or not hasattr(graph_client, "_g"):
        return {"ok": True, "backend": "none", "marked": 0, "skipped": True}

    rule_id = str(payload.get("rule_id") or "").strip()
    raw_ids = payload.get("entity_ids")
    entity_ids = [str(x).strip() for x in raw_ids if x is not None and str(x).strip()] if isinstance(raw_ids, list) else []

    import asyncio

    marked = 0
    for uid in entity_ids:
        ok = await asyncio.to_thread(
            _mark_user_high_risk_gremlin_sync,
            graph_client,
            uid,
            rule_id=rule_id,
        )
        if ok:
            marked += 1

    logger.info(
        "promotion_graph_hardening_complete rule_id=%s marked=%s requested=%s",
        rule_id,
        marked,
        len(entity_ids),
    )
    return {
        "ok": True,
        "backend": "janusgraph",
        "rule_id": rule_id,
        "requested": len(entity_ids),
        "marked": marked,
    }
