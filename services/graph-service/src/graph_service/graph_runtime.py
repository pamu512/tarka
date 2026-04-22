from __future__ import annotations
from typing import Any

from graph_service.config import settings

"""Dispatch graph persistence to Neo4j or JanusGraph based on GRAPH_BACKEND (no HTTP API changes)."""

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

        await store.create_link(tenant_id, from_external_id, to_external_id, relationship, properties)
        return
    from graph_service import neo4j_client as store

    await store.create_link(tenant_id, from_external_id, to_external_id, relationship, properties)


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    if settings.graph_backend == "janusgraph":
        from graph_service import janusgraph_store as store

        return await store.query_subgraph(tenant_id, entity_id, depth)
    from graph_service import neo4j_client as store

    return await store.query_subgraph(tenant_id, entity_id, depth)


async def close_graph_backend() -> None:
    if settings.graph_backend == "janusgraph":
        from graph_service.janusgraph_gremlin import close_janus_connection

        close_janus_connection()
        return
    from graph_service.neo4j_client import close_driver

    await close_driver()
