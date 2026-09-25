"""Observe draft list + loop scoreboard aliases. Wraps file shadow packs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from auth_rbac import require_role
from decision_api.effectiveness_tick import load_suggestions, run_effectiveness_tick
from decision_api.gnn_loop.receipts import load_receipts
from decision_api.loop_metrics import (
    compute_loop_metrics,
    load_ai_gate_counts,
    load_evaluations_for_tenant,
)
from decision_api.shadow import get_observations
from decision_api.y_label_store import load_label_records

router = APIRouter(prefix="/v1/observe", tags=["observe-drafts"])


def _l2_items() -> list[dict[str, Any]]:
    from decision_api.rule_api import _read_all_packs

    return [
        p
        for p in _read_all_packs()
        if p.get("source_key")
        or (p.get("evidence") or {}).get("leftover_id")
        or (p.get("evidence") or {}).get("hil_event_id")
        or (p.get("evidence") or {}).get("intent") == "soften"
    ]


@router.get("/drafts")
async def list_observe_drafts(state: str | None = Query(default=None)):
    want = (state or "").strip()
    items = _l2_items()
    if want:
        items = [
            p
            for p in items
            if str((p.get("lifecycle") or {}).get("state") or "") == want
        ]
    return {"items": items}


@router.get("/demote-suggestions")
async def get_demote_suggestions(
    tenant_id: str = Query(..., min_length=1, max_length=128),
):
    return {"suggestions": load_suggestions(tenant_id)}


@router.get("/loop-metrics")
async def get_loop_metrics(tenant_id: str = Query(..., min_length=1, max_length=128)):
    blocked, passed = load_ai_gate_counts()
    return compute_loop_metrics(
        _l2_items(),
        load_label_records(tenant_id),
        ai_blocked=blocked,
        ai_passed=passed,
        tenant_id=tenant_id,
        observations=get_observations(10000),
        receipts=load_receipts(tenant_id),
        evaluations=load_evaluations_for_tenant(tenant_id),
    )


ops_router = APIRouter(prefix="/v1/ops", tags=["observe-drafts"])


@ops_router.post("/effectiveness-tick")
async def post_effectiveness_tick(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    dry_run: bool = Query(default=False),
):
    from decision_api.rule_api import _read_all_packs

    return run_effectiveness_tick(
        _read_all_packs(),
        get_observations(10000),
        load_label_records(tenant_id),
        tenant_id=tenant_id,
        persist=not dry_run,
    )


@ops_router.get("/bakeoff")
async def get_bakeoff(tenant_id: str = Query(..., min_length=1, max_length=128)):
    return await get_loop_metrics(tenant_id)


@ops_router.get("/arena/config")
async def get_arena_config(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role("analyst")),
):
    """Read the tenant's challenger arena config (audit surface)."""
    from decision_api.challenger_arena import load_arena_config

    cfg = load_arena_config(tenant_id)
    if cfg is None:
        return {"configured": False, "challengers": {}}
    return {"configured": True, **cfg.to_store()}


@ops_router.put("/arena/config")
async def put_arena_config(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    body: dict = Body(...),
    _user=Depends(require_role("admin")),
):
    """Replace the tenant's challenger arena config (governed write).

    Admin-only: challengers run in shadow on live evaluate traffic, so wiring
    one is a governed act. Body: {"challengers": {name: <pack>}}. Packs must
    be dict rule-pack JSON (same schema the desk authors); shadow-only.
    """
    import json as _json
    import re as _re

    from decision_api.challenger_arena import _arena_rules_dir

    challengers = body.get("challengers")
    if not isinstance(challengers, dict) or not challengers:
        raise HTTPException(
            status_code=422, detail="body must be {'challengers': {name: pack}}"
        )
    safe = _re.sub(r"[^A-Za-z0-9_-]", "", tenant_id)[:64]
    if not safe:
        raise HTTPException(status_code=422, detail="invalid tenant_id")
    for name, pack in challengers.items():
        if not isinstance(name, str) or not name or len(name) > 64:
            raise HTTPException(
                status_code=422, detail=f"bad challenger name: {name!r}"
            )
        if not isinstance(pack, dict):
            raise HTTPException(
                status_code=422, detail=f"challenger {name}: pack must be an object"
            )
    arena_dir = _arena_rules_dir()
    arena_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_id": "tarka.challenger_arena/v1",
        "tenant_id": tenant_id,
        "challengers": challengers,
    }
    (arena_dir / f"{safe}.json").write_text(
        _json.dumps(payload, indent=2), encoding="utf-8"
    )
    return {"configured": True, "challengers": list(challengers)}


@ops_router.get("/arena/report")
async def get_arena_report(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(500, ge=1, le=5000),
):
    """Weekly-champion report over the tenant's arena ledger (P2).

    Reduces shadow challenger records to divergence/fp-delta with explicit
    unknowns (null) when labels are absent. Challenger packs themselves are
    configured via the arena store; this endpoint is read-only reporting.
    """
    from decision_api.challenger_arena import weekly_champion_report

    ledger = await _load_arena_ledger(tenant_id, limit)
    return weekly_champion_report(tenant_id, ledger)


async def _load_arena_ledger(tenant_id: str, limit: int) -> list[dict]:
    """Load recent arena shadow records. Records are appended by the evaluate
    pipeline when a tenant has challengers configured; absent store = empty
    ledger (report surfaces n=0, not an error)."""
    import json as _json
    from pathlib import Path as _Path

    from decision_api.calibration_api import _data_dir as _cal_dir

    path = _Path(_cal_dir()) / f"arena_ledger_{tenant_id}.jsonl"
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    except OSError:
        return []
    return rows[-limit:]


@ops_router.get("/queue-seam")
async def get_queue_seam():
    from decision_api.queue_seam import last_queue_status

    return last_queue_status()


@ops_router.get("/enforcement-mode")
async def get_enforcement_mode():
    from decision_api.enforcement import enforcement_mode

    mode = enforcement_mode()
    return {
        "enforcement_mode": mode,
        "authority": mode == "handoff",
        "default": "emit_only",
    }
