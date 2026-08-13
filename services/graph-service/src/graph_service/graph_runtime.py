from __future__ import annotations

import json
from typing import Any

from .config import settings

"""Dispatch graph persistence to Neo4j or JanusGraph based on GRAPH_BACKEND (no HTTP API changes)."""


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
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.upsert_entity(tenant_id, entity_type, external_id, properties, tags=tags)
    from graph_service import neo4j_client as store

    return await store.upsert_entity(tenant_id, entity_type, external_id, properties, tags=tags)


async def update_tags(tenant_id: str, external_id: str, tags: list[str]) -> list[str]:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.update_tags(tenant_id, external_id, tags)
    from graph_service import neo4j_client as store

    return await store.update_tags(tenant_id, external_id, tags)


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.get_tags(tenant_id, external_id)
    from graph_service import neo4j_client as store

    return await store.get_tags(tenant_id, external_id)


async def create_link(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        await store.create_link(
            tenant_id, from_external_id, to_external_id, relationship, properties
        )
        return
    from graph_service import neo4j_client as store

    await store.create_link(tenant_id, from_external_id, to_external_id, relationship, properties)


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.query_subgraph(tenant_id, entity_id, depth)
    from graph_service import neo4j_client as store

    return await store.query_subgraph(tenant_id, entity_id, depth)


async def query_entity_deep_context(tenant_id: str, external_id: str) -> dict[str, Any] | None:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.query_entity_deep_context(tenant_id, external_id)
    from graph_service import neo4j_client as store

    return await store.query_entity_deep_context(tenant_id, external_id)


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


async def close_graph_backend() -> None:
    if settings.graph_backend == "janusgraph":
        from .janusgraph_gremlin import close_janus_connection

        close_janus_connection()
        return
    from .neo4j_client import close_driver

    await close_driver()
