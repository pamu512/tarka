"""Observe draft list + loop scoreboard aliases. Wraps file shadow packs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from decision_api.loop_metrics import compute_loop_metrics, load_ai_gate_counts
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


@router.get("/loop-metrics")
async def get_loop_metrics(tenant_id: str = Query(..., min_length=1, max_length=128)):
    blocked, passed = load_ai_gate_counts()
    return compute_loop_metrics(
        _l2_items(),
        load_label_records(tenant_id),
        ai_blocked=blocked,
        ai_passed=passed,
    )
