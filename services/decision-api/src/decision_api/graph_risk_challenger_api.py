"""HTTP surface for graph-risk / ring-score challenger (A readiness + B/C lifecycle)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from decision_api.gnn_loop.lifecycle import (
    SidecarLifecycleError,
    enable_shadow,
    retire_shadow,
    run_export,
    run_train,
)
from decision_api.gnn_loop.readiness import build_graph_risk_readiness

router = APIRouter(tags=["graph-risk-challenger"])


class EnableShadowIn(BaseModel):
    shadow_url: str = Field(..., min_length=1, max_length=512)


def _actor(x_actor: str | None) -> str:
    return (x_actor or "").strip()


def _raise(exc: SidecarLifecycleError) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "detail": exc.detail},
    )


@router.get("/v1/ops/graph-risk-challenger")
async def graph_risk_challenger(
    tenant_id: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    """Labels + bars only. Does not train or set GRAPH_GNN_BETA_URL."""
    return build_graph_risk_readiness(tenant_id)


@router.post("/v1/ops/graph-risk-challenger/export")
async def graph_risk_export(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> dict[str, Any]:
    try:
        return run_export(tenant_id, actor=_actor(x_actor))
    except SidecarLifecycleError as e:
        _raise(e)
        raise


@router.post("/v1/ops/graph-risk-challenger/train")
async def graph_risk_train(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> dict[str, Any]:
    """Fixed gnn_loop recipe. No architecture knobs. Audit via X-Actor."""
    try:
        return run_train(tenant_id, actor=_actor(x_actor))
    except SidecarLifecycleError as e:
        _raise(e)
        raise


@router.post("/v1/ops/graph-risk-challenger/enable-shadow")
async def graph_risk_enable_shadow(
    body: EnableShadowIn,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> dict[str, Any]:
    """Enable shadow URL only when holdout serve_allowed. Not live DENY."""
    try:
        return enable_shadow(tenant_id, shadow_url=body.shadow_url, actor=_actor(x_actor))
    except SidecarLifecycleError as e:
        _raise(e)
        raise


@router.post("/v1/ops/graph-risk-challenger/retire")
async def graph_risk_retire(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> dict[str, Any]:
    try:
        return retire_shadow(tenant_id, actor=_actor(x_actor))
    except SidecarLifecycleError as e:
        _raise(e)
        raise
