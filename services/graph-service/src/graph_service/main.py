import logging
import os
import sys
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from graph_service.algorithms import (
    compute_entity_risk,
    detect_communities,
    detect_fraud_rings,
    find_shared_attributes,
    propagate_risk,
)
from graph_service.checkpoint_registry import (
    registry_public_view,
    reload_checkpoint_registry,
)
from graph_service.custom_schema import (
    TenantSchema,
    invalidate_cache,
    load_tenant_schema,
    save_tenant_schema,
)
from graph_service.graph_risk_model import score_graph_risk_beta
from graph_service.graph_runtime import (
    close_graph_backend,
    create_link,
    get_tags,
    query_subgraph,
    update_tags,
    upsert_entity,
)

log = logging.getLogger(__name__)

_BENCHMARK_RUNS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_MAX_BENCHMARK_RUNS = 200


def _store_benchmark_run(payload: dict[str, Any]) -> None:
    rid = str(payload.get("run_id") or "")
    if not rid:
        return
    _BENCHMARK_RUNS[rid] = payload
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
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
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
    await enforce_tenant_access(request, allowed_tenants=tenant_map.get(header, set()) if tenant_map else None)


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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        log.exception("create_link failed")
        raise HTTPException(status_code=502, detail="Unable to create graph link") from None
    return {"ok": True}


@app.get("/v1/subgraph")
async def subgraph(entity_id: str, tenant_id: str, depth: int = 2):
    data = await query_subgraph(tenant_id, entity_id, depth)
    return data


# ---------- schema endpoints ----------


class SchemaUpdateRequest(BaseModel):
    entity_types: list[str] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)
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
    return {"entities": result}


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


@app.get("/v1/analytics/entity-risk")
async def entity_risk_endpoint(tenant_id: str, entity_id: str, checkpoint: str | None = None):
    """Optional ``checkpoint`` selects graph profile (OSS #49). See GET /v1/checkpoint-profiles."""
    base = await compute_entity_risk(tenant_id, entity_id, checkpoint=checkpoint)
    beta = await score_graph_risk_beta(tenant_id, entity_id)
    if isinstance(beta, dict):
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
    return base


@app.get("/v1/analytics/ring-suspicion", response_model=RingSuspicionResponse)
async def ring_suspicion_endpoint(tenant_id: str, entity_id: str, min_ring_size: int = 3):
    """Mule/ring heuristic summary combining entity risk and ring samples."""
    risk = await compute_entity_risk(tenant_id, entity_id)
    rings = await detect_fraud_rings(tenant_id, min_ring_size=min_ring_size)
    ring_samples = [r for r in rings if entity_id in [str(x) for x in (r.get("ring_members") or [])]][:3]
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
    from graph_service.benchmark.datasets import list_tasks

    return list_tasks()


@app.get("/v1/benchmark/features")
async def benchmark_features_export():
    from graph_service.benchmark.registry import export_for_decision_pipeline, registry_content_digest

    out = export_for_decision_pipeline()
    out["content_digest"] = registry_content_digest()
    return out


@app.post("/v1/benchmark/runs", status_code=201)
async def benchmark_runs_create(body: BenchmarkRunRequest):
    from graph_service.benchmark.runner import run_experiment

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
