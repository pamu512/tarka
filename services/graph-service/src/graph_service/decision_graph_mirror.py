"""Optional mirror of Decision records into Janus/Neo4j/AGE for subgraph UX.

ponytail: fire-and-forget thread; failures are logged only. SoR remains SQLite.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

log = logging.getLogger("graph-service.decision_mirror")


def mirror_enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_JANUS_MIRROR") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def schedule_mirror(tenant_id: str, decision: dict[str, Any]) -> None:
    if not mirror_enabled():
        return
    threading.Thread(
        target=_run_mirror,
        args=(tenant_id, dict(decision)),
        daemon=True,
        name="decision-janus-mirror",
    ).start()


def _run_mirror(tenant_id: str, decision: dict[str, Any]) -> None:
    try:
        asyncio.run(_mirror_async(tenant_id, decision))
    except Exception:
        log.warning(
            "decision_janus_mirror_failed id=%s", decision.get("external_id"), exc_info=True
        )


async def _mirror_async(tenant_id: str, decision: dict[str, Any]) -> None:
    from graph_service.graph_runtime import create_link, upsert_entity

    did = str(decision.get("external_id") or "")
    if not did:
        return
    props = {
        "kind": decision.get("kind"),
        "category": decision.get("category"),
        "scenario": decision.get("scenario"),
        "outcome": decision.get("outcome"),
        "reasoning": decision.get("reasoning"),
        "trace_id": decision.get("trace_id"),
        "case_id": decision.get("case_id"),
        "agent_run_id": decision.get("agent_run_id"),
        "created_at": decision.get("created_at"),
        "shadow": decision.get("shadow"),
    }
    if decision.get("confidence") is not None:
        props["confidence"] = decision.get("confidence")
    await upsert_entity(tenant_id, "Decision", did, props, tags=["decision_context"])
    for eid in decision.get("entity_external_ids") or []:
        ee = str(eid).strip()
        if not ee:
            continue
        try:
            await create_link(tenant_id, did, ee, "BASED_ON", {"source": "decision_context"})
        except Exception:
            log.debug("decision_mirror_based_on_skip from=%s to=%s", did, ee, exc_info=True)
