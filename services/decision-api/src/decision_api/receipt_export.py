"""Receipt + late-label export. Buyer loads the warehouse. Tarka does not host it."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from auth_rbac import require_role
from decision_api.db import get_session
from decision_api.models import AuditRecord
from decision_api.y_label_store import load_label_records

router = APIRouter(prefix="/v1/exports", tags=["exports"])
TRAINING_ROW_SCHEMA = "tarka.training_row/v1"


def _parse_bound(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "invalid_time", "detail": raw}
        ) from exc


def join_training_rows(
    receipts: list[dict[str, Any]], labels: dict[str, Any]
) -> list[dict[str, Any]]:
    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    costs = labels.get("fp_cost_by_trace") if isinstance(labels, dict) else {}
    costs = costs if isinstance(costs, dict) else {}
    labeled_at = labels.get("labeled_at_by_trace") if isinstance(labels, dict) else {}
    labeled_at = labeled_at if isinstance(labeled_at, dict) else {}
    by_token: dict[str, dict[str, Any]] = {}
    for rec in receipts:
        token = str(rec.get("evaluation_token") or rec.get("trace_id") or "").strip()
        if token:
            by_token[token] = rec
    rows: list[dict[str, Any]] = []
    for token, kind in kinds.items():
        rec = by_token.get(str(token))
        if rec is None:
            continue
        rows.append(
            {
                "schema_id": TRAINING_ROW_SCHEMA,
                "evaluation_token": token,
                "tenant_id": rec.get("tenant_id"),
                "entity_id": rec.get("entity_id"),
                "label_kind": kind,
                "fp_cost": costs.get(token),
                "labeled_at": labeled_at.get(token),
                "pack_hash": rec.get("pack_hash"),
                "action": rec.get("decision") or rec.get("action"),
                "features_ref": rec.get("features_ref"),
            }
        )
    return rows


def receipt_row_from_audit(rec: AuditRecord) -> dict[str, Any]:
    snap = rec.payload_snapshot if isinstance(rec.payload_snapshot, dict) else {}
    token = str(snap.get("evaluation_token") or rec.trace_id or "").strip()
    return {
        "evaluation_token": token,
        "trace_id": str(rec.trace_id),
        "tenant_id": rec.tenant_id,
        "entity_id": rec.entity_id,
        "event_type": rec.event_type,
        "decision": rec.decision,
        "score": rec.score,
        "pack_hash": snap.get("pack_hash") or snap.get("rule_pack_file"),
        "features_ref": snap.get("features_ref"),
        "action": snap.get("enforcement_action") or rec.decision,
        "hop_summary": (snap.get("graph_hop_v1") or {}).get("status")
        if isinstance(snap.get("graph_hop_v1"), dict)
        else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.get("/receipts")
async def export_receipts(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    from_ts: str = Query(..., alias="from"),
    to_ts: str = Query(..., alias="to"),
    session=Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    start = _parse_bound(from_ts)
    end = _parse_bound(to_ts)
    if end < start:
        raise HTTPException(400, detail={"code": "invalid_window"})
    result = await session.execute(
        select(AuditRecord).where(
            AuditRecord.tenant_id == tenant_id,
            AuditRecord.created_at >= start,
            AuditRecord.created_at <= end,
        )
    )
    receipts = [receipt_row_from_audit(r) for r in result.scalars().all()]
    labels = load_label_records(tenant_id)
    return {
        "schema_id": "tarka.receipt_label_export/v1",
        "tenant_id": tenant_id,
        "receipts": receipts,
        "labels": labels,
        "training_rows": join_training_rows(receipts, labels),
    }


def write_jsonl(path: Any, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
