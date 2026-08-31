from __future__ import annotations

import json
import logging
from typing import Any

from .config import settings

log = logging.getLogger("graph-service.runtime")

"""Dispatch graph persistence to Neo4j, JanusGraph, or AGE based on GRAPH_BACKEND (no HTTP API changes)."""

_TRACE_ID_CAP = 32


def merge_stored_trace_ids(existing_raw: Any, incoming: Any) -> list[str]:
    """Accumulate evaluate traces on an object. Last 32 unique ids; incoming order wins tail."""

    def _as_list(raw: Any) -> list[str]:
        if raw is None:
            return []
        parsed: Any = raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                s = raw.strip()
                return [s] if s else []
        if isinstance(parsed, list):
            out: list[str] = []
            for item in parsed:
                s = str(item).strip()
                if s and s not in out:
                    out.append(s)
            return out
        s = str(parsed).strip()
        return [s] if s else []

    merged: list[str] = []
    for item in _as_list(existing_raw) + _as_list(incoming):
        if item not in merged:
            merged.append(item)
    return merged[-_TRACE_ID_CAP:]


def parse_p90_degree_by_label(raw: Any, label: str) -> int | None:
    try:
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            raw = json.loads(text)
        elif not isinstance(raw, dict):
            raw = dict(raw)
        val = raw.get(label)
        if val is None:
            return None
        return int(val)
    except Exception:
        return None


async def upsert_entity(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None = None,
) -> str:
    gid = await _store().upsert_entity(tenant_id, entity_type, external_id, properties, tags=tags)
    try:
        from .search_keys import upsert_search_keys

        await upsert_search_keys(tenant_id, entity_type, external_id, properties)
    except Exception:
        log.warning("search_keys_upsert_failed entity=%s", external_id, exc_info=True)
    return gid


async def update_tags(tenant_id: str, external_id: str, tags: list[str]) -> list[str]:
    return await _store().update_tags(tenant_id, external_id, tags)


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    return await _store().get_tags(tenant_id, external_id)


async def create_link(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    await _store().create_link(
        tenant_id, from_external_id, to_external_id, relationship, properties
    )
    if relationship == "RESULTED_IN":
        try:
            await trim_allow_decision_window(tenant_id, from_external_id)
        except Exception:
            log.warning(
                "allow_decision_trim_failed tenant=%s person=%s",
                tenant_id,
                from_external_id,
                exc_info=True,
            )


async def delete_entity(tenant_id: str, external_id: str) -> None:
    await _store().delete_entity(tenant_id, external_id)


# ponytail: same rule as tarka_shared.decision_graph_payload.allow_decision_ids_over_cap.
# graph-service image does not ship shared-core; keep the picker here until it does.
_ALLOW_AGE_CAP = 20


def allow_decision_ids_over_cap(
    nodes: list[dict[str, Any]], *, cap: int = _ALLOW_AGE_CAP
) -> list[str]:
    allows: list[tuple[str, str]] = []
    for node in nodes:
        labels = node.get("labels") or []
        etype = str(node.get("entity_type") or "")
        if etype != "Decision" and "Decision" not in [str(x) for x in labels]:
            continue
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        kind = str(props.get("kind") or "").strip().lower()
        outcome = str(props.get("outcome") or "").strip().lower()
        source = str(props.get("source") or "").strip().lower()
        material = (
            kind in {"human_disposition", "policy_gate"}
            or outcome
            in {
                "deny",
                "review",
                "held",
                "hold",
            }
            or outcome.startswith("resolved")
        )
        if material:
            continue
        if source != "evaluate" or outcome != "allow":
            continue
        eid = str(
            node.get("id") or node.get("external_id") or props.get("external_id") or ""
        ).strip()
        if not eid:
            continue
        allows.append((str(props.get("created_at") or ""), eid))
    allows.sort(key=lambda row: (row[0], row[1]))
    if len(allows) <= cap:
        return []
    return [eid for _, eid in allows[:-cap]]


async def trim_allow_decision_window(tenant_id: str, person_id: str) -> int:
    """Drop oldest evaluate-allow Decision hops until the Person is at the cap."""
    pid = str(person_id or "").strip()
    if not pid:
        return 0
    sub = await query_subgraph(tenant_id, pid, 1)
    drop = allow_decision_ids_over_cap(list(sub.get("nodes") or []))
    for eid in drop:
        try:
            await delete_entity(tenant_id, eid)
        except Exception:
            log.warning("allow_decision_delete_failed id=%s", eid, exc_info=True)
    return len(drop)


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.list_one_hop_ids(tenant_id, entity_id)
    if settings.graph_backend == "age":
        from graph_service import age_client as store

        return await store.list_one_hop_ids(tenant_id, entity_id)
    from graph_service import neo4j_client as store

    return await store.list_one_hop_ids(tenant_id, entity_id)


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    return await _store().query_subgraph(tenant_id, entity_id, depth)


async def query_entity_deep_context(tenant_id: str, external_id: str) -> dict[str, Any] | None:
    return await _store().query_entity_deep_context(tenant_id, external_id)


async def set_entity_risk_properties(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        await store.set_entity_risk_properties(tenant_id, entity_id, props)
        return
    if settings.graph_backend == "age":
        from graph_service import age_client as store

        await store.set_entity_risk_properties(tenant_id, entity_id, props)
        return
    from graph_service import neo4j_client as store

    await store.set_entity_risk_properties(tenant_id, entity_id, props)


async def load_peer_p90_by_label(tenant_id: str, label: str) -> int | None:
    try:
        if settings.graph_backend == "janusgraph":
            from graph_service import janusgraph_store as store

            return await store.load_peer_p90_by_label(tenant_id, label)
        if settings.graph_backend == "age":
            from graph_service import age_client as store

            return await store.load_peer_p90_by_label(tenant_id, label)
        from graph_service import neo4j_client as store

        return await store.load_peer_p90_by_label(tenant_id, label)
    except Exception:
        return None


def _store():
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return store
    if settings.graph_backend == "age":
        from graph_service import age_client as store

        return store
    from graph_service import neo4j_client as store

    return store


async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .search_keys import search_prefix

    sql = await search_prefix(tenant_id, q, label=label, limit=limit)
    if settings.graph_backend == "age":
        return sql if sql is not None else ([], False)
    if sql is not None:
        return sql
    rows, _trunc = await _store().search_entities(tenant_id, q, label=label, limit=limit)
    return rows, True


async def list_entity_risk_top(
    tenant_id: str, limit: int = 50, min_score: float = 0
) -> list[dict[str, Any]]:
    return await _store().list_entity_risk_top(tenant_id, limit=limit, min_score=min_score)


async def scan_tenant_entity_ids(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    return await _store().scan_tenant_entity_ids(tenant_id, limit)


async def upsert_graph_risk_stats(
    tenant_id: str, p90_degree_by_label: dict[str, int], stats_computed_at: str
) -> None:
    await _store().upsert_graph_risk_stats(tenant_id, p90_degree_by_label, stats_computed_at)


async def close_graph_backend() -> None:
    if settings.graph_backend == "janusgraph":
        from .janusgraph_gremlin import close_janus_connection

        close_janus_connection()
        return
    if settings.graph_backend == "age":
        from .age_client import close_driver as close_age

        await close_age()
        return
    from .neo4j_client import close_driver

    await close_driver()
