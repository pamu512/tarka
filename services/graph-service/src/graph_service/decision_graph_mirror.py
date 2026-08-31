"""Mirror Decision records into Janus/Neo4j/AGE for subgraph UX.

Failures are logged only. SoR remains SQLite. Must run on the service event
loop — asyncpg's pool cannot be used from asyncio.run() in a thread.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("graph-service.decision_mirror")


def mirror_enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_JANUS_MIRROR") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _synthesize_decision_object(decision: dict[str, Any]) -> dict[str, Any] | None:
    did = str(decision.get("external_id") or "").strip()
    if not did:
        return None
    return {
        "external_id": did,
        "entity_type": "Decision",
        "properties": {
            "kind": str(decision.get("kind") or ""),
            "source": "evaluate"
            if str(decision.get("kind") or "") == "evaluate"
            else "disposition",
            "outcome": str(decision.get("outcome") or ""),
            "trace_id": str(decision.get("trace_id") or ""),
            "created_at": str(decision.get("created_at") or ""),
            "markings": list(decision.get("markings") or ["desk"]),
            "rule_ids": list(decision.get("rule_ids") or [])[:32],
            "last_trace_id": str(decision.get("trace_id") or ""),
            "trace_ids": [str(decision.get("trace_id") or "")]
            if str(decision.get("trace_id") or "").strip()
            else [],
        },
    }


def _person_id(decision: dict[str, Any], objects: list[dict[str, Any]]) -> str:
    for obj in objects:
        if str(obj.get("entity_type") or "") == "Person":
            eid = str(obj.get("external_id") or "").strip()
            if eid:
                return eid
    for raw in decision.get("entity_external_ids") or []:
        s = str(raw or "").strip()
        if s and not s.startswith("dec:"):
            return s
    return ""


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
    objects = [raw for raw in (decision.get("objects") or []) if isinstance(raw, dict)]
    links = [raw for raw in (decision.get("object_links") or []) if isinstance(raw, dict)]
    if not any(str(obj.get("entity_type") or "") == "Decision" for obj in objects):
        synth = _synthesize_decision_object(decision)
        if synth:
            objects.append(synth)
            person = _person_id(decision, objects)
            if person and not any(
                str(lk.get("relationship") or "") == "RESULTED_IN"
                and str(lk.get("to_external_id") or "") == did
                for lk in links
            ):
                links.append(
                    {
                        "from_external_id": person,
                        "to_external_id": did,
                        "relationship": "RESULTED_IN",
                    }
                )
    for raw in objects:
        oid = str(raw.get("external_id") or "").strip()
        etype = str(raw.get("entity_type") or "Custom").strip() or "Custom"
        if not oid:
            continue
        oprops = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        try:
            await upsert_entity(tenant_id, etype, oid, dict(oprops), tags=["evaluate_object"])
        except Exception:
            log.debug("decision_mirror_object_skip id=%s", oid, exc_info=True)
    for raw in links:
        src = str(raw.get("from_external_id") or "").strip()
        dst = str(raw.get("to_external_id") or "").strip()
        rel = str(raw.get("relationship") or "RELATED").strip() or "RELATED"
        if not src or not dst:
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
