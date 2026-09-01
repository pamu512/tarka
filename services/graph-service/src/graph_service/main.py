import logging
import os
import sys
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from graph_contract import (
    UnsignedGraphToken,
    empty_graph_answers,
    graph_answers_from_neighborhood,
)

from .algorithms import (
    compute_entity_risk,
    detect_communities,
    detect_fraud_rings,
    explain_paths,
    find_shared_attributes,
    propagate_risk,
)
from .explainability_usage import record_explainability_event, usage_snapshot
from .checkpoint_registry import (
    registry_public_view,
    reload_checkpoint_registry,
)
from .custom_schema import (
    TenantSchema,
    invalidate_cache,
    load_tenant_schema,
    save_tenant_schema,
)
from .entity_risk_score import clamp_search_limit, is_found_payload
from .decision_markings import filter_subgraph_for_read, parse_caller_markings
from .object_attention import attention_for_node, score_object_attention, stats_from_subgraph
from .entity_risk_writeback import (
    EntityRiskNotFound,
    clamp_refresh_limit,
    clamp_top_limit,
    persist_entity_risk,
    refresh_entity,
    refresh_tenant,
    refresh_touched_and_neighbors,
)
from .graph_risk_model import score_graph_risk_beta
from .schemas import EntityRiskResponse
from .graph_runtime import (
    close_graph_backend,
    create_link,
    get_tags,
    list_entity_risk_top,
    query_entity_deep_context,
    query_subgraph,
    search_entities,
    update_tags,
    upsert_entity,
)
from .mapped_ingest import MappedIngestRequest, ingest_mapped_object
from .hunt_net import apply_hunt_net, clamp_lookback_days

log = logging.getLogger(__name__)

_BENCHMARK_RUNS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_MAX_BENCHMARK_RUNS = 200


def _store_benchmark_run(payload: dict[str, Any]) -> None:
    rid = str(payload.get("run_id") or "")
    if not rid:
        return
    # ponytail: process memory only — ceiling is restart loss; upgrade path is Postgres/CH
    stored = {
        **payload,
        "durability": "process_memory",
        "storage_mode": "in_process_ordered_dict",
    }
    _BENCHMARK_RUNS[rid] = stored
    while len(_BENCHMARK_RUNS) > _MAX_BENCHMARK_RUNS:
        _BENCHMARK_RUNS.popitem(last=False)


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from auth_rbac import require_role  # noqa: E402
from observability import setup_observability  # noqa: E402
from tenant_binding import enforce_tenant_access, parse_api_key_tenant_map  # noqa: E402

# ---------- auth ----------


def _get_api_keys() -> frozenset[str]:
    raw = os.environ.get("API_KEYS", "").strip()
    return frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()


async def require_api_key(request: Request) -> None:
    if request.url.path in {"/v1/health", "/metrics"}:
        return
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    tenant_map = parse_api_key_tenant_map()
    await enforce_tenant_access(
        request, allowed_tenants=tenant_map.get(header, set()) if tenant_map else None
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_graph_backend()


app = FastAPI(
    title="Tarka Graph Service",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "graph-service")

from .decision_context_api import router as decision_context_router  # noqa: E402

app.include_router(decision_context_router)


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
    from_entity_type: str | None = None
    to_entity_type: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class TagsRequest(BaseModel):
    tenant_id: str
    tags: list[str]


class AttentionObjectIn(BaseModel):
    external_id: str
    entity_type: str = "Custom"
    on_this_event: bool = False


class ObjectsAttentionRequest(BaseModel):
    tenant_id: str
    objects: list[AttentionObjectIn] = Field(default_factory=list, max_length=16)


class RingSuspicionResponse(BaseModel):
    tenant_id: str
    entity_id: str
    suspicion_level: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    ring_samples: list[dict[str, Any]] = Field(default_factory=list)


class BenchmarkRunRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    task_id: str
    y_true: list[int]
    baseline_scores: list[float]
    graph_scores: list[float]


@app.get("/v1/health")
async def health():
    from .decision_context_api import decision_graph_enabled
    from .decision_context_store import _db_path

    dg_enabled = decision_graph_enabled()
    db_path = _db_path()
    return {
        "status": "ok",
        "decision_graph": {
            "enabled": dg_enabled,
            "store": "sqlite",
            "db_path": str(db_path),
            "db_exists": db_path.exists(),
        },
    }


@app.get("/v1/entities/search")
async def entities_search(tenant_id: str, q: str = "", label: str | None = None, limit: int = 20):
    needle = (q or "").strip()[:256]
    if len(needle) < 2:
        return {"entities": [], "truncated": False}
    lab = (label or "").strip() or None
    rows, truncated = await search_entities(
        tenant_id, q=needle, label=lab, limit=clamp_search_limit(limit)
    )
    return {"entities": rows, "truncated": bool(truncated)}


def _subgraph_node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("entity_id") or node.get("external_id") or "")


def _entity_from_subgraph(data: dict[str, Any], external_id: str) -> dict[str, Any] | None:
    for node in data.get("nodes") or []:
        if isinstance(node, dict) and _subgraph_node_id(node) == external_id:
            return node
    return None


def _subgraph_for_read(data: dict[str, Any], request: Request) -> dict[str, Any]:
    return filter_subgraph_for_read(
        data, parse_caller_markings(request.headers.get("x-graph-markings"))
    )


def _decision_hops_from_subgraph(data: dict[str, Any], person_id: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for node in data.get("nodes") or []:
        if isinstance(node, dict):
            nid = _subgraph_node_id(node)
            if nid:
                by_id[nid] = node
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict) or str(edge.get("type") or "") != "RESULTED_IN":
            continue
        frm = str(edge.get("from_id") or "")
        to = str(edge.get("to_id") or "")
        other = to if frm == person_id else frm if to == person_id else ""
        if not other or other in seen:
            continue
        node = by_id.get(other) or {}
        labels = [str(x) for x in (node.get("labels") or [])]
        if "Decision" not in labels:
            continue
        seen.add(other)
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        out.append(
            {
                "id": other,
                "outcome": props.get("outcome"),
                "source": props.get("source"),
                "kind": props.get("kind"),
                "trace_id": props.get("trace_id"),
                "created_at": props.get("created_at"),
            }
        )
    return out


def _attention_for_neighbors(seed_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    rows: list[dict[str, Any]] = []
    for node in nodes:
        nid = _subgraph_node_id(node)
        if not nid or nid == seed_id:
            continue
        labels = [str(x) for x in (node.get("labels") or [])]
        if "Person" in labels:
            continue
        fanout = int(node.get("relation_count") or 0)
        hot = 0
        factors = node.get("risk_factors") or []
        if isinstance(factors, list):
            for factor in factors:
                s = str(factor)
                if s.startswith("connected_flagged:"):
                    try:
                        hot = int(s.split(":", 1)[1])
                    except (TypeError, ValueError):
                        hot = 0
        if not fanout:
            fanout = 1
        row = attention_for_node(
            node,
            person_fanout=fanout,
            review_or_deny_neighbors=hot,
            on_this_event=False,
        )
        rows.append(row)
    rows.sort(key=lambda r: (-int(r.get("importance") or 0), str(r.get("entity_id") or "")))
    return rows


async def _attention_for_object(
    tenant_id: str, external_id: str, entity_type: str, on_this_event: bool
) -> dict[str, Any]:
    data = await query_subgraph(tenant_id, external_id, 1)
    node = _entity_from_subgraph(data, external_id)
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    fanout, hot = stats_from_subgraph(external_id, nodes)
    if node is None:
        row = score_object_attention(
            entity_type=entity_type,
            person_fanout=0,
            review_or_deny_neighbors=0,
            on_this_event=on_this_event,
        )
        row["entity_id"] = external_id
        row["entity_type"] = entity_type or "Custom"
        row["found"] = False
        return row
    row = attention_for_node(
        node,
        person_fanout=fanout,
        review_or_deny_neighbors=hot,
        on_this_event=on_this_event,
    )
    row["found"] = True
    return row


@app.get("/v1/entities/{external_id}")
async def get_entity(external_id: str, tenant_id: str, request: Request):
    data = _subgraph_for_read(await query_subgraph(tenant_id, external_id, 1), request)
    node = _entity_from_subgraph(data, external_id)
    if node is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return node


@app.get("/v1/entities/{external_id}/links")
async def get_entity_links(external_id: str, tenant_id: str, request: Request):
    data = _subgraph_for_read(await query_subgraph(tenant_id, external_id, 1), request)
    if _entity_from_subgraph(data, external_id) is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return {
        "entity_id": external_id,
        "nodes": data.get("nodes") or [],
        "edges": data.get("edges") or [],
        "attention": _attention_for_neighbors(external_id, data),
    }


@app.post("/v1/objects/attention")
async def objects_attention(body: ObjectsAttentionRequest):
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in body.objects[:16]:
        eid = str(item.external_id or "").strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        rows.append(
            await _attention_for_object(body.tenant_id, eid, item.entity_type, item.on_this_event)
        )
    rows.sort(key=lambda r: (-int(r.get("importance") or 0), str(r.get("entity_id") or "")))
    return {"tenant_id": body.tenant_id, "attention": rows}


@app.get("/v1/entities/{external_id}/history")
async def get_entity_history(external_id: str, tenant_id: str, request: Request):
    data = _subgraph_for_read(await query_subgraph(tenant_id, external_id, 1), request)
    node = _entity_from_subgraph(data, external_id)
    if node is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    traces = props.get("trace_ids")
    if not isinstance(traces, list):
        last = props.get("last_trace_id")
        traces = [last] if last else []
    return {
        "entity_id": external_id,
        "last_trace_id": props.get("last_trace_id"),
        "trace_ids": [str(t) for t in traces if t],
        "decisions": _decision_hops_from_subgraph(data, external_id),
        "properties": props,
    }


@app.post("/v1/entities", response_model=EntityResponse)
async def upsert_entity_endpoint(body: UpsertEntityRequest):
    try:
        gid = await upsert_entity(
            body.tenant_id,
            body.entity_type,
            body.external_id,
            body.properties,
            tags=body.tags,
        )
    except UnsignedGraphToken as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        await refresh_touched_and_neighbors(body.tenant_id, [body.external_id])
    except Exception:
        log.exception(
            "mutation risk refresh failed after upsert tenant=%s entity=%s",
            body.tenant_id,
            body.external_id,
        )
    return EntityResponse(
        graph_id=gid,
        entity_type=body.entity_type,
        external_id=body.external_id,
    )


@app.post("/v1/ingest/objects")
async def ingest_mapped_objects(body: MappedIngestRequest):
    """Second writer: map a foreign record onto the same Person evaluate uses."""
    try:
        out = await ingest_mapped_object(body)
    except UnsignedGraphToken as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        await refresh_touched_and_neighbors(out["tenant_id"], [out["person_id"], out["object_id"]])
    except Exception:
        log.exception(
            "mutation risk refresh failed after mapped ingest tenant=%s person=%s",
            out["tenant_id"],
            out["person_id"],
        )
    return out


@app.post("/v1/entities/{external_id}/tags")
async def update_entity_tags(external_id: str, body: TagsRequest):
    result = await update_tags(body.tenant_id, external_id, body.tags)
    try:
        await refresh_touched_and_neighbors(body.tenant_id, [external_id])
    except Exception:
        log.exception(
            "mutation risk refresh failed after tags tenant=%s entity=%s",
            body.tenant_id,
            external_id,
        )
    return {"tags": result}


@app.get("/v1/entities/{external_id}/tags")
async def get_entity_tags(external_id: str, tenant_id: str):
    result = await get_tags(tenant_id, external_id)
    return {"tags": result}


@app.get("/v1/entities/{external_id}/deep-context")
async def entity_deep_context(external_id: str, tenant_id: str, request: Request):
    """Deep neighborhood context for analysts (transactions, IPs, risk snapshot).

    Returns ``404`` when the entity is not present in the graph database for the tenant.
    Hunt Decision ACL: no intersecting markings → 404, same as GET /entities.
    """
    gated = _subgraph_for_read(await query_subgraph(tenant_id, external_id, 1), request)
    if _entity_from_subgraph(gated, external_id) is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    data = await query_entity_deep_context(tenant_id, external_id)
    if data is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    try:
        risk = await compute_entity_risk(tenant_id, external_id)
    except Exception:
        log.exception("deep-context risk failed tenant=%s entity=%s", tenant_id, external_id)
        risk = {}
    factors = risk.get("risk_factors") if isinstance(risk.get("risk_factors"), list) else []
    data["risk_history"] = [
        {
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "risk_score": risk.get("risk_score"),
            "risk_factors": factors,
            "source": "current_entity_risk",
        }
    ]
    return data


@app.post("/v1/links")
async def links_endpoint(body: LinkRequest):
    try:
        props = dict(body.properties or {})
        if body.from_entity_type:
            props["from_vtype"] = body.from_entity_type
        if body.to_entity_type:
            props["to_vtype"] = body.to_entity_type
        await create_link(
            body.tenant_id,
            body.from_external_id,
            body.to_external_id,
            body.relationship,
            props,
        )
    except UnsignedGraphToken as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        log.exception("create_link failed")
        raise HTTPException(status_code=502, detail="Unable to create graph link") from None
    try:
        await refresh_touched_and_neighbors(
            body.tenant_id, [body.from_external_id, body.to_external_id]
        )
    except Exception:
        log.exception(
            "mutation risk refresh failed after link tenant=%s from=%s to=%s",
            body.tenant_id,
            body.from_external_id,
            body.to_external_id,
        )
    return {"ok": True}


@app.get("/v1/subgraph")
async def subgraph(
    entity_id: str,
    tenant_id: str,
    request: Request,
    depth: int = 2,
    lookback_days: int | None = None,
    types: str | None = None,
):
    data = _subgraph_for_read(await query_subgraph(tenant_id, entity_id, depth), request)
    lb = clamp_lookback_days(lookback_days)
    type_list = [part.strip() for part in (types or "").split(",") if part.strip()] or None
    if lb is None and type_list is None:
        return data
    return apply_hunt_net(data, seed_id=entity_id, lookback_days=lb, types=type_list)


# ---------- schema endpoints ----------


class SchemaUpdateRequest(BaseModel):
    entity_types: list[str] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    typed_edges: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional hetero constraints: relationship + allowed endpoint entity types (xFraud-style).",
    )
    node_context_hints: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Suggested transaction-context property keys per entity type (documentation / UI hints).",
    )
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
        typed_edges=body.typed_edges or None,
        node_context_hints=body.node_context_hints or None,
        roles=body.roles or None,
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
        tenant_id,
        entity_id,
        depth=depth,
        decay=decay,
    )
    record_explainability_event("risk_propagation", tenant_id)
    return {"entities": result}


@app.get("/v1/analytics/path-explain")
async def path_explain_endpoint(
    tenant_id: str,
    from_entity_id: str,
    to_entity_id: str | None = None,
    depth: int = 3,
    decay: float = 0.5,
    limit: int = 10,
):
    """Ranked graph paths with path_description and risk narrative (Q2-E03)."""
    out = await explain_paths(
        tenant_id,
        from_entity_id,
        depth=depth,
        decay=decay,
        to_entity_id=to_entity_id,
        limit=limit,
    )
    record_explainability_event("path_explain", tenant_id)
    return out


@app.get("/v1/analytics/explainability/usage")
async def explainability_usage_endpoint(_=Depends(require_role("analyst"))):
    """Server-side explainability surface counters since process boot."""
    return usage_snapshot()


@app.get("/v1/analytics/shared-attributes")
async def shared_attributes_endpoint(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
):
    try:
        return await find_shared_attributes(
            tenant_id,
            attribute=attribute,
            min_shared=min_shared,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/analytics/fraud-rings")
async def fraud_rings_endpoint(tenant_id: str, min_size: int = 3):
    result = await detect_fraud_rings(tenant_id, min_ring_size=min_size)
    return {"rings": result}


@app.get("/v1/analytics/entity-risk", response_model=EntityRiskResponse)
async def entity_risk_endpoint(tenant_id: str, entity_id: str, checkpoint: str | None = None):
    """Optional ``checkpoint`` selects graph profile (OSS #49). See GET /v1/checkpoint-profiles."""
    base = await compute_entity_risk(tenant_id, entity_id, checkpoint=checkpoint)
    try:
        sub = await query_subgraph(tenant_id, entity_id, 2)
        answers = graph_answers_from_neighborhood(
            entity_id,
            list(sub.get("nodes") or []),
            list(sub.get("edges") or []),
        )
        base.update(answers)
    except Exception:
        log.exception("graph answers attach failed tenant=%s entity=%s", tenant_id, entity_id)
        base.update(empty_graph_answers())
    # Beta may overwrite score/factors; growth always comes from compute.
    growth = {
        "relation_count": base.get("relation_count", 0),
        "relation_growth_1h": base.get("relation_growth_1h", 0),
        "relation_growth_24h": base.get("relation_growth_24h", 0),
    }
    beta = await score_graph_risk_beta(tenant_id, entity_id)
    if is_found_payload(base) and isinstance(beta, dict):
        try:
            beta_score = max(0.0, min(100.0, float(beta.get("risk_score", 0.0))))
        except (TypeError, ValueError):
            beta_score = 0.0
        base_score = float(base.get("risk_score", 0.0))
        if beta_score > base_score:
            base["risk_score"] = round(beta_score, 2)
            reasons = list(base.get("risk_factors") or [])
            reasons.append("gnn_beta_high_risk")
            base["risk_factors"] = list(dict.fromkeys(str(x) for x in reasons if str(x).strip()))
        base["gnn_beta"] = beta
    base.update(growth)
    base["scored"] = is_found_payload(base)
    if base["scored"]:
        try:
            await persist_entity_risk(tenant_id, entity_id, base)
        except Exception:
            log.exception(
                "entity-risk write-through failed tenant=%s entity=%s",
                tenant_id,
                entity_id,
            )
    return EntityRiskResponse.model_validate(base)


class EntityRiskRefreshRequest(BaseModel):
    tenant_id: str
    entity_id: str | None = None
    limit: int | None = None


@app.get("/v1/analytics/entity-risk/top")
async def entity_risk_top(tenant_id: str, limit: int = 50, min_score: float = 0):
    rows = await list_entity_risk_top(tenant_id, limit=clamp_top_limit(limit), min_score=min_score)
    return {"entities": rows}


@app.post("/v1/analytics/entity-risk/refresh")
async def entity_risk_refresh(body: EntityRiskRefreshRequest):
    if body.entity_id:
        try:
            return await refresh_entity(
                body.tenant_id, body.entity_id, compute_fn=compute_entity_risk
            )
        except EntityRiskNotFound:
            raise HTTPException(status_code=404, detail="entity_not_found") from None
    limit = clamp_refresh_limit(body.limit if body.limit is not None else 5000)
    return await refresh_tenant(body.tenant_id, limit=limit)


@app.get("/v1/analytics/ring-suspicion", response_model=RingSuspicionResponse)
async def ring_suspicion_endpoint(tenant_id: str, entity_id: str, min_ring_size: int = 3):
    """Mule/ring heuristic summary combining entity risk and ring samples."""
    risk = await compute_entity_risk(tenant_id, entity_id)
    rings = await detect_fraud_rings(tenant_id, min_ring_size=min_ring_size)
    ring_samples = [
        r for r in rings if entity_id in [str(x) for x in (r.get("ring_members") or [])]
    ][:3]
    reasons = [str(x) for x in (risk.get("risk_factors") or []) if str(x).strip()]
    if ring_samples:
        reasons.append("entity_present_in_detected_ring")
    score = float(risk.get("risk_score", 0.0))
    if ring_samples:
        score = min(100.0, score + 12.0)
    if score >= 75:
        suspicion_level = "high"
    elif score >= 45:
        suspicion_level = "medium"
    else:
        suspicion_level = "low"
    return RingSuspicionResponse(
        tenant_id=tenant_id,
        entity_id=entity_id,
        suspicion_level=suspicion_level,
        score=round(score, 2),
        reasons=list(dict.fromkeys(reasons)),
        ring_samples=ring_samples,
    )


@app.get("/v1/checkpoint-profiles")
async def get_checkpoint_profiles():
    """Registry of checkpoint → graph analytics profile (multipliers, hop hints)."""
    return registry_public_view()


@app.post("/v1/admin/checkpoint-profiles/reload")
async def reload_checkpoint_profiles(_=Depends(require_role("admin"))):
    reload_checkpoint_registry()
    return {"ok": True, **registry_public_view()}


# ---------- DGFraud-style benchmark harness (#64–#66) ----------


@app.get("/v1/benchmark/datasets")
async def benchmark_datasets():
    from benchmark.datasets import list_tasks

    return list_tasks()


@app.get("/v1/benchmark/features")
async def benchmark_features_export():
    from benchmark.registry import (
        export_for_decision_pipeline,
        registry_content_digest,
    )

    out = export_for_decision_pipeline()
    out["content_digest"] = registry_content_digest()
    return out


@app.post("/v1/benchmark/runs", status_code=201)
async def benchmark_runs_create(body: BenchmarkRunRequest):
    from benchmark.runner import run_experiment

    try:
        scorecard = run_experiment(
            seed=body.seed,
            task_id=body.task_id,
            y_true=body.y_true,
            baseline_scores=body.baseline_scores,
            graph_scores=body.graph_scores,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _store_benchmark_run(scorecard)
    return scorecard


@app.get("/v1/benchmark/runs/{run_id}")
async def benchmark_runs_get(run_id: str):
    row = _BENCHMARK_RUNS.get(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return row
