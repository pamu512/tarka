import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from graph_service.neo4j_client import (
    close_driver,
    create_link,
    get_tags,
    query_subgraph,
    update_tags,
    upsert_entity,
)
from graph_service.custom_schema import (
    TenantSchema,
    load_tenant_schema,
    save_tenant_schema,
    invalidate_cache,
)
from graph_service.algorithms import (
    compute_entity_risk,
    detect_communities,
    detect_fraud_rings,
    find_shared_attributes,
    propagate_risk,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from observability import setup_observability  # noqa: E402

# ---------- auth ----------

_valid_api_keys: frozenset[str] | None = None

def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = os.environ.get("API_KEYS", "").strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys

async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        return
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_driver()


app = FastAPI(
    title="Tarka Graph Service",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "graph-service")


class UpsertEntityRequest(BaseModel):
    tenant_id: str
    entity_type: str
    external_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] | None = None


class EntityResponse(BaseModel):
    graph_id: str
    entity_type: str
    external_id: str


class LinkRequest(BaseModel):
    tenant_id: str
    from_external_id: str
    to_external_id: str
    relationship: str
    properties: dict[str, Any] = Field(default_factory=dict)


class TagsRequest(BaseModel):
    tenant_id: str
    tags: list[str]


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/entities", response_model=EntityResponse)
async def upsert_entity_endpoint(body: UpsertEntityRequest):
    gid = await upsert_entity(
        body.tenant_id,
        body.entity_type,
        body.external_id,
        body.properties,
        tags=body.tags,
    )
    return EntityResponse(
        graph_id=gid,
        entity_type=body.entity_type,
        external_id=body.external_id,
    )


@app.post("/v1/entities/{external_id}/tags")
async def update_entity_tags(external_id: str, body: TagsRequest):
    result = await update_tags(body.tenant_id, external_id, body.tags)
    return {"tags": result}


@app.get("/v1/entities/{external_id}/tags")
async def get_entity_tags(external_id: str, tenant_id: str):
    result = await get_tags(tenant_id, external_id)
    return {"tags": result}


@app.post("/v1/links")
async def links_endpoint(body: LinkRequest):
    try:
        await create_link(
            body.tenant_id,
            body.from_external_id,
            body.to_external_id,
            body.relationship,
            body.properties,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@app.get("/v1/subgraph")
async def subgraph(entity_id: str, tenant_id: str, depth: int = 2):
    data = await query_subgraph(tenant_id, entity_id, depth)
    return data


# ---------- schema endpoints ----------


class SchemaUpdateRequest(BaseModel):
    entity_types: list[str] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/schema/{tenant_id}")
async def get_schema(tenant_id: str):
    schema = load_tenant_schema(tenant_id)
    return schema.to_dict()


@app.put("/v1/schema/{tenant_id}")
async def put_schema(tenant_id: str, body: SchemaUpdateRequest):
    invalidate_cache(tenant_id)
    schema = TenantSchema(
        tenant_id=tenant_id,
        entity_types=body.entity_types or None,
        relationship_types=body.relationship_types or None,
        extra=body.extra,
    )
    save_tenant_schema(schema)
    return schema.to_dict()


# ---------- analytics endpoints ----------


@app.get("/v1/analytics/communities")
async def communities_endpoint(tenant_id: str, min_size: int = 3):
    result = await detect_communities(tenant_id, min_community_size=min_size)
    return {"communities": result}


@app.get("/v1/analytics/risk-propagation")
async def risk_propagation_endpoint(
    tenant_id: str,
    entity_id: str,
    depth: int = 3,
    decay: float = 0.5,
):
    result = await propagate_risk(
        tenant_id, entity_id, depth=depth, decay=decay,
    )
    return {"entities": result}


@app.get("/v1/analytics/shared-attributes")
async def shared_attributes_endpoint(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
):
    try:
        return await find_shared_attributes(
            tenant_id, attribute=attribute, min_shared=min_shared,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/analytics/fraud-rings")
async def fraud_rings_endpoint(tenant_id: str, min_size: int = 3):
    result = await detect_fraud_rings(tenant_id, min_ring_size=min_size)
    return {"rings": result}


@app.get("/v1/analytics/entity-risk")
async def entity_risk_endpoint(tenant_id: str, entity_id: str):
    return await compute_entity_risk(tenant_id, entity_id)
