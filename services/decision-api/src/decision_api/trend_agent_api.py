"""Ops surface for the trend agent (RAG → triage + PENDING_VALIDATION drafts)."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402
from analytics import trend_store  # noqa: E402
from analytics.trend_agent import TrendAgent, run_trend_evaluation  # noqa: E402
from analytics.trend_rag import normalize_window_rows  # noqa: E402
from analytics.trend_windows import build_window_rows_or_none  # noqa: E402

log = logging.getLogger("decision-api.trend")

router = APIRouter(prefix="/v1/ops/trend", tags=["trend-agent"])


class TrendEvaluateBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    entity_id: str = Field(..., min_length=1, max_length=512)
    region_code: str = ""
    window_rows: list[dict[str, Any]] | dict[str, Any] | None = None
    skip_llm: bool | None = None


class TrendHilBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    entity_id: str = Field(..., min_length=1, max_length=512)
    override_type: str = Field(..., min_length=1, max_length=128)
    scope_key: str = ""
    analyst_rationale: str = ""


class TrendWatchBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    entity_id: str = Field(..., min_length=1, max_length=512)
    reason: str = ""


class TrendTickBody(BaseModel):
    tenant_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    skip_llm: bool | None = None
    entity_ids: list[str] | None = None


def _require_window_rows(raw: Any) -> list[dict[str, Any]]:
    rows = normalize_window_rows(raw)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "window_rows_required",
                "message": (
                    "Provide at least one valid window row "
                    "(metric_key, window, observed, baseline_mean). "
                    "Baselines are never invented."
                ),
            },
        )
    return rows


def _tick_skip_llm(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return (os.environ.get("TREND_TICK_SKIP_LLM") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "",
    }


async def _features_for_entity(tenant_id: str, entity_id: str) -> dict[str, Any]:
    """Load Redis aggregate features; empty dict on failure (never invent baselines)."""
    try:
        from decision_api import main as decision_main

        agg = getattr(decision_main, "agg_store", None)
        if agg is None:
            return {}
        return dict(await agg.compute_features(tenant_id, entity_id, {}))
    except Exception as exc:
        log.warning(
            "trend_tick_features_failed tenant=%s entity=%s exc=%r",
            tenant_id,
            entity_id,
            exc,
        )
        return {}


@router.post("/evaluate")
async def trend_evaluate(
    body: TrendEvaluateBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    rows = _require_window_rows(body.window_rows)
    result = await run_trend_evaluation(
        body.tenant_id.strip(),
        body.entity_id.strip(),
        region_code=body.region_code,
        window_rows=rows,
        skip_llm=body.skip_llm,
    )
    draft_id = result.get("draft_rule_id")
    if draft_id:
        draft = trend_store.get_draft_rule(
            tenant_id=body.tenant_id.strip(), draft_id=str(draft_id)
        )
        pkg = (draft or {}).get("rule_package") if isinstance(draft, dict) else None
        if isinstance(pkg, dict) and pkg.get("wasm_ready") is True:
            raise HTTPException(
                status_code=500,
                detail="trend_draft_must_not_claim_wasm_ready",
            )
        if isinstance(pkg, dict) and pkg.get("promotable") is True:
            raise HTTPException(
                status_code=500,
                detail="trend_draft_must_not_claim_promotable",
            )
    return result


@router.get("/drafts")
async def trend_list_drafts(
    tenant_id: str,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id required")
    return {"tenant_id": tid, "drafts": trend_store.list_pending_drafts(tenant_id=tid)}


@router.post("/drafts/{draft_id}/reject")
async def trend_reject_draft(
    draft_id: str,
    tenant_id: str,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    did = (draft_id or "").strip()
    if not tid or not did:
        raise HTTPException(status_code=400, detail="tenant_id and draft_id required")
    row = trend_store.reject_draft_rule(tenant_id=tid, draft_id=did)
    if row is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return {"ok": True, "draft": row}


@router.post("/drafts/{draft_id}/promote")
async def trend_promote_draft_forbidden(
    draft_id: str,
    tenant_id: str,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Explicit refuse — fulfills 'never live Wasm promote' as an enforceable API."""
    tid = (tenant_id or "").strip()
    did = (draft_id or "").strip()
    payload = trend_store.refuse_promote_draft(tenant_id=tid, draft_id=did)
    raise HTTPException(status_code=409, detail=payload)


@router.post("/hil-override")
async def trend_hil_override(
    body: TrendHilBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    oid = TrendAgent(skip_llm=True).apply_feedback_override(
        body.tenant_id.strip(),
        body.entity_id.strip(),
        body.override_type.strip(),
        scope_key=body.scope_key,
        analyst_rationale=body.analyst_rationale,
    )
    return {"ok": True, "override_id": oid}


@router.post("/watch")
async def trend_watch(
    body: TrendWatchBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    trend_store.upsert_watch(
        tenant_id=body.tenant_id.strip(),
        entity_id=body.entity_id.strip(),
        reason=body.reason,
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id.strip(),
        "entity_id": body.entity_id.strip(),
    }


@router.get("/watch")
async def trend_list_watch(
    tenant_id: str | None = None,
    limit: int = 50,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    return {"items": trend_store.list_watch(tenant_id=tenant_id, limit=limit)}


@router.get("/posture")
async def trend_posture(
    tenant_id: str | None = None,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Ops honesty snapshot for production readiness panels."""
    tid = (tenant_id or "").strip() or None
    drafts = trend_store.list_pending_drafts(tenant_id=tid) if tid else []
    watch = trend_store.list_watch(tenant_id=tid, limit=20)
    return {
        "schema_id": "tarka.trend_ops_posture/v1",
        "wasm_auto_promote": False,
        "tick_skip_llm_default": _tick_skip_llm(None),
        "baseline_min_n": trend_store.baseline_min_n(),
        "watch_count": len(watch),
        "pending_draft_count": len(drafts) if tid else None,
        "tenant_id": tid,
        "honesty": (
            "Drafts stay PENDING_VALIDATION (wasm_ready=false). "
            "Baselines are EWMA of prior observations — never invented. "
            "Promote endpoint always returns 409 never_auto_promote."
        ),
        "tick_entrypoint": "POST /v1/ops/trend/tick",
        "cron_hint": "scripts/trend_tick_loop.sh or compose profile trend-tick",
    }


@router.post("/tick")
async def trend_tick(
    body: TrendTickBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    skip = _tick_skip_llm(body.skip_llm)
    tid_filter = (body.tenant_id or "").strip() or None
    results: list[dict[str, Any]] = []
    evaluated = 0
    skipped = 0

    if body.entity_ids:
        targets = [
            {
                "tenant_id": tid_filter or "unknown",
                "entity_id": str(e).strip(),
                "reason": "explicit",
            }
            for e in body.entity_ids
            if str(e).strip()
        ]
        if not tid_filter:
            raise HTTPException(
                status_code=400,
                detail="tenant_id required when entity_ids provided",
            )
        targets = [{**t, "tenant_id": tid_filter} for t in targets][: body.limit]
    else:
        targets = trend_store.list_watch(tenant_id=tid_filter, limit=body.limit)

    for item in targets:
        tenant_id = str(item["tenant_id"])
        entity_id = str(item["entity_id"])
        features = await _features_for_entity(tenant_id, entity_id)
        rows, meta = build_window_rows_or_none(
            tenant_id=tenant_id,
            entity_id=entity_id,
            features=features,
            record=True,
        )
        if rows is None:
            skipped += 1
            results.append(
                {
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "status": "skipped",
                    "skip_reason": meta.get("skip_reason"),
                    "meta": meta,
                }
            )
            continue
        out = await run_trend_evaluation(
            tenant_id,
            entity_id,
            window_rows=rows,
            skip_llm=skip,
        )
        evaluated += 1
        results.append(
            {
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "status": "evaluated",
                "disposition": out.get("disposition"),
                "draft_rule_id": out.get("draft_rule_id"),
                "triage_ticket_id": out.get("triage_ticket_id"),
                "skip_llm": skip,
            }
        )

    return {
        "ok": True,
        "evaluated": evaluated,
        "skipped": skipped,
        "skip_llm": skip,
        "results": results,
    }
