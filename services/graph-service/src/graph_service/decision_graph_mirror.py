"""Optional mirror of Decision records into Janus/Neo4j/AGE for subgraph UX.

Failures are logged only. SoR remains SQLite. Must run on the service event
loop — asyncpg's pool cannot be used from asyncio.run() in a thread.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("graph-service.decision_mirror")


def mirror_enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_JANUS_MIRROR") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def schedule_mirror(
    tenant_id: str,
    decision: dict[str, Any],
    *,
    objects: list[dict[str, Any]] | None = None,
    object_links: list[dict[str, Any]] | None = None,
) -> None:
    if not mirror_enabled():
        return
    row = dict(decision)
    if objects is not None:
        row["objects"] = objects
    if object_links is not None:
        row["object_links"] = object_links
    try:
        await _mirror_async(tenant_id, row)
    except Exception:
        log.warning(
            "decision_janus_mirror_failed id=%s", decision.get("external_id"), exc_info=True
        )


async def _mirror_async(tenant_id: str, decision: dict[str, Any]) -> None:
    from graph_service.graph_runtime import create_link, upsert_entity

    did = str(decision.get("external_id") or "")
    if not did:
        return
    # Evaluate is a fact on the object (last_outcome / last_trace_id). A Decision
    # vertex per receipt would grow without bound.
    for raw in decision.get("objects") or []:
        if not isinstance(raw, dict):
            continue
        oid = str(raw.get("external_id") or "").strip()
        etype = str(raw.get("entity_type") or "Custom").strip() or "Custom"
        if not oid or etype == "Decision":
            continue
        oprops = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        try:
            await upsert_entity(tenant_id, etype, oid, dict(oprops), tags=["evaluate_object"])
        except Exception:
            log.debug("decision_mirror_object_skip id=%s", oid, exc_info=True)
    for raw in decision.get("object_links") or []:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from_external_id") or "").strip()
        dst = str(raw.get("to_external_id") or "").strip()
        rel = str(raw.get("relationship") or "RELATED").strip() or "RELATED"
        if not src or not dst or src == did or dst == did or rel in {"RESULTED_IN", "BASED_ON"}:
            continue
        try:
            await create_link(
                tenant_id,
                src,
                dst,
                rel,
                {"source": "evaluate", "trace_id": decision.get("trace_id")},
            )
        except Exception:
            log.debug("decision_mirror_link_skip from=%s to=%s", src, dst, exc_info=True)
