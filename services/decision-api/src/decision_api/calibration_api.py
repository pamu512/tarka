from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402

from decision_api.config import settings  # noqa: E402
from decision_api.db import get_session  # noqa: E402
from decision_api.models import AuditRecord  # noqa: E402
from decision_api.label_join import (  # noqa: E402
    apply_y_labels,
    label_coverage_posture,
    y_label_from_ground_truth,
)
from decision_api.reliability_export import (  # noqa: E402
    RELIABILITY_CSV_FIELDS,
    audit_row_to_export_dict,
    reliability_bins,
    rows_to_csv,
)
from decision_api.rule_label_metrics import rule_precision_after_labels  # noqa: E402
from decision_api.y_label_store import load_y_labels, merge_y_labels  # noqa: E402

"""Calibration snapshots, drift hints, and reliability export (Wave 1 trust)."""
router = APIRouter(prefix="/v1/calibration", tags=["calibration"])

_EXPORT_MAX = 50_000


def _data_dir() -> Path:
    base = os.environ.get("CALIBRATION_DATA_DIR", "").strip()
    if base:
        p = Path(base)
    else:
        p = Path(settings.rules_path) / "calibration_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshots_path() -> Path:
    return _data_dir() / "snapshots.jsonl"


def _references_path() -> Path:
    return _data_dir() / "references.json"


def _safe_profile(profile: str) -> str:
    return (
        "".join(c if c.isalnum() or c in "._-" else "_" for c in profile.strip())[:120]
        or "default"
    )


def _load_reference_map() -> dict[str, dict[str, Any]]:
    path = _references_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, dict):
            out[key] = value
    return out


def _save_reference_map(data: dict[str, dict[str, Any]]) -> None:
    _references_path().write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )


class CalibrationSnapshotIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    profile: str = Field(default="default", max_length=64)
    schema_version: str = Field(default="3", max_length=16)
    expected_calibration_version: int = Field(default=1, ge=1)
    sample_count: int = Field(ge=1, le=1_000_000)
    """Approximate number of decisions represented (batch aggregate)."""
    integrity_histogram: dict[str, int] = Field(
        default_factory=dict,
        description='Counts per bin label, e.g. {"0.0-0.2": 10, "0.2-0.4": 20, ...}',
    )
    mean_integrity: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_final_score: float | None = Field(default=None, ge=0.0, le=100.0)
    notes: str | None = Field(default=None, max_length=512)


@router.post("/snapshots", status_code=201)
async def append_snapshot(body: CalibrationSnapshotIn):
    """Append a calibration snapshot (typically from an offline batch or ETL job)."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenant_id": body.tenant_id,
        "profile": _safe_profile(body.profile),
        "schema_version": body.schema_version,
        "expected_calibration_version": body.expected_calibration_version,
        "sample_count": body.sample_count,
        "integrity_histogram": body.integrity_histogram,
        "mean_integrity": body.mean_integrity,
        "mean_final_score": body.mean_final_score,
        "notes": body.notes,
    }
    p = _snapshots_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return {
        "ok": True,
        "id": hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16],
    }


@router.post("/reference/{profile}")
async def set_reference(profile: str, body: CalibrationSnapshotIn):
    """Pin a golden reference distribution for drift comparison."""
    safe_profile = _safe_profile(profile)
    ref = {
        "profile": safe_profile,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "integrity_histogram": body.integrity_histogram,
        "mean_integrity": body.mean_integrity,
        "sample_count": body.sample_count,
    }
    refs = _load_reference_map()
    refs[safe_profile] = ref
    _save_reference_map(refs)
    return {"ok": True, "profile": safe_profile, "path": str(_references_path())}


def compute_drift_for_tenant(
    tenant_id: str,
    profile: str,
) -> dict[str, Any]:
    """Pure helper for tests and tooling."""
    safe_profile = _safe_profile(profile)
    refs = _load_reference_map()
    ref = refs.get(safe_profile)
    if not ref:
        return {
            "tenant_id": tenant_id,
            "profile": safe_profile,
            "drift_score": None,
            "hint": "no_reference_set",
            "reference_path": str(_references_path()),
        }
    ref_hist = ref.get("integrity_histogram") or {}
    latest: dict[str, Any] | None = None
    sp = _snapshots_path()
    if sp.is_file():
        for line in reversed(sp.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_profile = _safe_profile(str(row.get("profile") or "default"))
            if row.get("tenant_id") == tenant_id and row_profile == safe_profile:
                latest = row
                break
    if not latest:
        return {
            "tenant_id": tenant_id,
            "profile": safe_profile,
            "drift_score": None,
            "hint": "no_snapshots_for_tenant",
        }
    cur_hist = latest.get("integrity_histogram") or {}
    keys = sorted(set(ref_hist.keys()) | set(cur_hist.keys()))
    if not keys:
        return {
            "tenant_id": tenant_id,
            "profile": safe_profile,
            "drift_score": None,
            "hint": "empty_histograms",
        }
    total_r = sum(int(ref_hist.get(k, 0)) for k in keys)
    total_c = sum(int(cur_hist.get(k, 0)) for k in keys)
    if total_r <= 0 or total_c <= 0:
        return {
            "tenant_id": tenant_id,
            "profile": safe_profile,
            "drift_score": None,
            "hint": "insufficient_mass",
        }
    drift = 0.0
    for k in keys:
        pr = ref_hist.get(k, 0) / total_r
        pc = cur_hist.get(k, 0) / total_c
        drift += abs(pr - pc)
    drift = round(drift / max(len(keys), 1), 4)
    hint = "ok"
    if drift > 0.25:
        hint = "elevated_bin_shift_review_calibration"
    elif drift > 0.15:
        hint = "moderate_drift_monitor"
    return {
        "tenant_id": tenant_id,
        "profile": safe_profile,
        "drift_score": drift,
        "hint": hint,
        "latest_ts": latest.get("ts"),
        "reference_set_at": ref.get("set_at"),
    }


@router.get("/drift")
async def drift_hint(tenant_id: str, profile: str = "default"):
    """Compare latest snapshot to reference; return a small drift score for ops dashboards."""
    out = compute_drift_for_tenant(tenant_id, profile)
    try:
        from observability import get_metrics

        hint = str(out.get("hint") or "")
        metrics = get_metrics()
        if hint == "elevated_bin_shift_review_calibration":
            metrics.inc("tarka_calibration_drift_hint_elevated")
        elif hint == "moderate_drift_monitor":
            metrics.inc("tarka_calibration_drift_hint_moderate")
    except Exception:
        pass
    return out


@router.get("/summary")
async def summary(tenant_id: str, profile: str = "default", limit: int = 20):
    """Last N snapshots for tenant/profile (for Trust Center / debugging)."""
    sp = _snapshots_path()
    safe_profile = _safe_profile(profile)
    out: list[dict[str, Any]] = []
    if not sp.is_file():
        return {"tenant_id": tenant_id, "profile": safe_profile, "snapshots": []}
    for line in reversed(sp.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_profile = _safe_profile(str(row.get("profile") or "default"))
        if row.get("tenant_id") == tenant_id and row_profile == safe_profile:
            out.append(row)
        if len(out) >= min(limit, 100):
            break
    return {"tenant_id": tenant_id, "profile": safe_profile, "snapshots": out}


def _enforce_tenant(request: Request, tenant_id: str) -> None:
    auth = getattr(request.state, "auth_user", None)
    if (
        auth
        and auth.tenant_ids
        and "*" not in auth.tenant_ids
        and tenant_id not in auth.tenant_ids
    ):
        raise HTTPException(403, "tenant not permitted for this credential")


async def _load_audit_export_rows(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), _EXPORT_MAX))
    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(lim)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()
    rows: list[dict[str, Any]] = []
    for rec in records:
        rows.append(
            {
                "trace_id": rec.trace_id,
                "tenant_id": rec.tenant_id,
                "entity_id": rec.entity_id,
                "event_type": rec.event_type,
                "decision": rec.decision,
                "score": rec.score,
                "rule_hits": list(rec.rule_hits or []),
                "payload_snapshot": rec.payload_snapshot,
                "created_at": rec.created_at,
            }
        )
    return rows


@router.get("/reliability-export.csv")
async def reliability_export_csv(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    limit: int = Query(10_000, ge=1, le=_EXPORT_MAX),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> Response:
    """CSV of decision_audit scores + inference_context for offline reliability curves.

    ``y_label`` is left empty for warehouse/case joins. ``proxy_label_from_decision``
    is a weak stand-in only — see ``GET /v1/calibration/reliability-bins`` caveat.
    """
    _enforce_tenant(request, tenant_id)
    rows = await _load_audit_export_rows(session, tenant_id=tenant_id, limit=limit)
    body = rows_to_csv(rows)
    filename = f"reliability_{tenant_id}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ReliabilityBinsBody(BaseModel):
    """Optional ground-truth map: trace_id → FRAUD/LEGITIMATE (or 0/1)."""

    labels_by_trace: dict[str, str] = Field(default_factory=dict)
    labels_by_entity: dict[str, str] = Field(default_factory=dict)
    # Critical regrade: proxy-as-truth is opt-in only.
    allow_proxy_labels: bool = False
    persist_labels: bool = True


def _normalize_label_maps(
    labels_by_trace: dict[str, str],
    labels_by_entity: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    by_t = {
        str(k).strip(): y_label_from_ground_truth(v)
        for k, v in (labels_by_trace or {}).items()
        if str(k).strip() and y_label_from_ground_truth(v)
    }
    by_e = {
        str(k).strip(): y_label_from_ground_truth(v)
        for k, v in (labels_by_entity or {}).items()
        if str(k).strip() and y_label_from_ground_truth(v)
    }
    return by_t, by_e


async def _reliability_bins_payload(
    *,
    request: Request,
    tenant_id: str,
    limit: int,
    n_bins: int,
    session: AsyncSession,
    labels_by_trace: dict[str, str] | None = None,
    labels_by_entity: dict[str, str] | None = None,
    allow_proxy_labels: bool = False,
    persist_incoming: bool = False,
) -> dict[str, Any]:
    _enforce_tenant(request, tenant_id)
    rows = await _load_audit_export_rows(session, tenant_id=tenant_id, limit=limit)
    export_rows = [audit_row_to_export_dict(r) for r in rows]
    by_t, by_e = _normalize_label_maps(labels_by_trace or {}, labels_by_entity or {})
    store_meta: dict[str, Any] | None = None
    if persist_incoming and (by_t or by_e):
        store_meta = merge_y_labels(tenant_id, by_trace=by_t, by_entity=by_e)
        by_t = dict(store_meta["by_trace"])
        by_e = dict(store_meta["by_entity"])
    else:
        stored = load_y_labels(tenant_id)
        # Incoming maps win over store for this request; store fills gaps.
        merged_t = {**stored["by_trace"], **by_t}
        merged_e = {**stored["by_entity"], **by_e}
        by_t, by_e = merged_t, merged_e
    join_meta = apply_y_labels(export_rows, by_t, labels_by_entity=by_e)
    try:
        payload = reliability_bins(
            export_rows, n_bins=n_bins, use_proxy_labels=allow_proxy_labels
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    posture = label_coverage_posture(
        label_coverage=float(payload.get("label_coverage") or 0.0),
        proxy_only=payload.get("label_source") == "proxy_from_decision",
    )
    payload["tenant_id"] = tenant_id
    payload["rows_scanned"] = len(export_rows)
    payload["csv_fields"] = list(RELIABILITY_CSV_FIELDS)
    payload["join"] = join_meta
    payload["posture"] = posture
    payload["stored_labels"] = {
        "trace_labels": len(by_t),
        "entity_labels": len(by_e),
        **({"persist": store_meta} if store_meta else {}),
    }
    return payload


@router.get("/reliability-bins")
async def reliability_export_bins(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    limit: int = Query(10_000, ge=1, le=_EXPORT_MAX),
    n_bins: int = Query(10, ge=2, le=50),
    allow_proxy_labels: bool = Query(False, description="Opt-in proxy labels (not ground truth)"),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Reliability bins joined with durable y_labels; proxy labels off by default."""
    return await _reliability_bins_payload(
        request=request,
        tenant_id=tenant_id,
        limit=limit,
        n_bins=n_bins,
        session=session,
        allow_proxy_labels=allow_proxy_labels,
        persist_incoming=False,
    )


@router.post("/reliability-bins")
async def reliability_export_bins_with_labels(
    body: ReliabilityBinsBody,
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    limit: int = Query(10_000, ge=1, le=_EXPORT_MAX),
    n_bins: int = Query(10, ge=2, le=50),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Join dispositions into y_label, optionally persist, refuse proxy-as-healthy by default."""
    return await _reliability_bins_payload(
        request=request,
        tenant_id=tenant_id,
        limit=limit,
        n_bins=n_bins,
        session=session,
        labels_by_trace=body.labels_by_trace,
        labels_by_entity=body.labels_by_entity,
        allow_proxy_labels=body.allow_proxy_labels,
        persist_incoming=body.persist_labels,
    )


@router.post("/rule-precision-after-labels")
async def rule_precision_after_labels_endpoint(
    body: ReliabilityBinsBody,
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    limit: int = Query(10_000, ge=1, le=_EXPORT_MAX),
    min_labeled_hits: int = Query(5, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Per-rule precision/FP after joining dispositions into y_label (bridge C3)."""
    _enforce_tenant(request, tenant_id)
    rows = await _load_audit_export_rows(session, tenant_id=tenant_id, limit=limit)
    export_rows = [audit_row_to_export_dict(r) for r in rows]
    for i, raw in enumerate(rows):
        export_rows[i]["rule_hits"] = list(raw.get("rule_hits") or [])
        export_rows[i]["decision"] = str(raw.get("decision") or "")
    by_t, by_e = _normalize_label_maps(body.labels_by_trace, body.labels_by_entity)
    if body.persist_labels and (by_t or by_e):
        store_meta = merge_y_labels(tenant_id, by_trace=by_t, by_entity=by_e)
        by_t = dict(store_meta["by_trace"])
        by_e = dict(store_meta["by_entity"])
    else:
        stored = load_y_labels(tenant_id)
        by_t = {**stored["by_trace"], **by_t}
        by_e = {**stored["by_entity"], **by_e}
    join_meta = apply_y_labels(export_rows, by_t, labels_by_entity=by_e)
    payload = rule_precision_after_labels(
        export_rows, min_labeled_hits=min_labeled_hits
    )
    payload["tenant_id"] = tenant_id
    payload["join"] = join_meta
    return payload


class YLabelMergeItem(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    y_label: str = Field(min_length=1, max_length=16)
    source: str | None = Field(default=None, max_length=64)


class YLabelMergeBody(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    labels: list[YLabelMergeItem] = Field(min_length=1, max_length=5000)


@router.post("/y-labels/merge")
async def merge_y_labels_endpoint(
    body: YLabelMergeBody,
    request: Request,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Merge trace-level y_labels into durable store (dispute / disposition feeds)."""
    _enforce_tenant(request, body.tenant_id)
    by_trace: dict[str, str] = {}
    skipped = 0
    sources: dict[str, int] = {}
    for item in body.labels:
        tid = str(item.trace_id).strip()
        y = y_label_from_ground_truth(item.y_label)
        if not y and str(item.y_label).strip() in {"0", "1"}:
            y = str(item.y_label).strip()
        if not tid or y not in {"0", "1"}:
            skipped += 1
            continue
        by_trace[tid] = y
        src = (item.source or "unknown").strip() or "unknown"
        sources[src] = sources.get(src, 0) + 1
    if not by_trace:
        raise HTTPException(status_code=400, detail="no valid labels to merge")
    store_meta = merge_y_labels(body.tenant_id, by_trace=by_trace)
    return {
        "ok": True,
        "schema_id": "tarka.y_labels_merge/v1",
        "tenant_id": body.tenant_id,
        "merged": len(by_trace),
        "skipped": skipped,
        "source_breakdown": sources,
        "store": store_meta,
    }


class ChallengeDispatchBody(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    decision: str = Field(default="review", max_length=64)
    recommended_action: str = Field(min_length=1, max_length=128)
    challenge_metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/challenge/dispatch")
async def dispatch_challenge_from_desk(
    body: ChallengeDispatchBody,
    request: Request,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Desk-executable step-up: fire tenant challenge webhook for recommended_action."""
    _enforce_tenant(request, body.tenant_id)
    from decision_api.challenge_orchestrator import (
        challenge_webhook_configured,
        maybe_dispatch_challenge_webhook,
    )
    from decision_api.enforcement import is_step_up_recommended

    if not is_step_up_recommended(body.recommended_action):
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "NOT_STEP_UP_ACTION",
                "message": f"recommended_action {body.recommended_action!r} is not a challenge class",
            },
        )
    if not challenge_webhook_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "CHALLENGE_WEBHOOK_UNCONFIGURED",
                "message": "Set TARKA_CHALLENGE_WEBHOOK_URL to enable desk challenge dispatch",
            },
        )
    async with httpx.AsyncClient() as http:
        result = await maybe_dispatch_challenge_webhook(
            http=http,
            trace_id=body.trace_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            decision=body.decision,
            recommended_action=body.recommended_action,
            challenge_metadata=body.challenge_metadata,
        )
    return {
        "schema_id": "tarka.challenge_dispatch/v1",
        "ok": bool(result and result.get("ok")),
        "delivery": result,
    }


@router.get("/shadow-promote-gate")
async def shadow_promote_gate(
    tenant_id: str | None = Query(None, description="Optional tenant for label/CC scan"),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Desk-facing promote-gate posture + label gate + CC agreement (P0-CC)."""
    from decision_api.champion_challenger_audit import (
        aggregate_champion_challenger,
        drift_promote_gate,
        label_gated_promote,
        mcnemar_promote_gate,
    )
    from decision_api.vertical_packs import evaluate_kill_criteria, get_vertical_pack

    pack = get_vertical_pack("fintech") or {}
    criteria = pack.get("kill_criteria") or {}
    blocked = evaluate_kill_criteria(
        {"precision": 0.01, "recall": 0.01, "false_positive_rate": 0.5},
        criteria,
        events_evaluated=5,
    )
    allowed = evaluate_kill_criteria(
        {
            "precision": float(criteria.get("min_precision", 0.5)) + 0.2,
            "recall": float(criteria.get("min_recall", 0.5)) + 0.2,
            "false_positive_rate": max(
                0.0, float(criteria.get("max_false_positive_rate", 0.2)) - 0.05
            ),
        },
        criteria,
        events_evaluated=int(criteria.get("min_events", 100)) + 50,
    )

    label_posture: dict[str, Any] = {
        "healthy": False,
        "status": "no_tenant",
        "label_coverage": 0.0,
        "hint": "Pass tenant_id to scan real-label coverage before promote.",
    }
    cc_audit: dict[str, Any] = aggregate_champion_challenger([])
    tid = (tenant_id or "").strip()
    if tid:
        try:
            stmt = (
                select(AuditRecord)
                .where(AuditRecord.tenant_id == tid)
                .order_by(AuditRecord.created_at.desc())
                .limit(500)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            export_rows = [
                audit_row_to_export_dict(
                    {
                        "trace_id": rec.trace_id,
                        "tenant_id": rec.tenant_id,
                        "entity_id": rec.entity_id,
                        "event_type": rec.event_type,
                        "decision": rec.decision,
                        "score": rec.score,
                        "payload_snapshot": rec.payload_snapshot,
                        "created_at": rec.created_at,
                    }
                )
                for rec in records
            ]
            bins = reliability_bins(export_rows, n_bins=10, use_proxy_labels=True)
            label_posture = label_coverage_posture(
                label_coverage=float(bins.get("label_coverage") or 0.0),
                proxy_only=bins.get("label_source") == "proxy_from_decision",
            )
            label_posture["label_source"] = bins.get("label_source")
            label_posture["rows_scanned"] = len(export_rows)
            cc_audit = aggregate_champion_challenger(
                [
                    {
                        "trace_id": str(rec.trace_id),
                        "payload_snapshot": rec.payload_snapshot
                        if isinstance(rec.payload_snapshot, dict)
                        else {},
                    }
                    for rec in records
                ]
            )
        except Exception:
            label_posture = {
                "healthy": False,
                "status": "label_coverage_unavailable",
                "label_coverage": 0.0,
                "hint": "audit scan failed",
            }

    # Desk bar: real labels + McNemar volume + elevated calibration drift block.
    live_promote = label_gated_promote(label_posture=label_posture, kill_gate=None)
    mcnemar = mcnemar_promote_gate(cc_audit)
    drift_row: dict[str, Any] = {"hint": "no_tenant"}
    if tid:
        drift_row = compute_drift_for_tenant(tid, "default")
    drift_gate = drift_promote_gate(drift_row)
    combined_blockers = (
        list(live_promote.get("blockers") or [])
        + list(mcnemar.get("blockers") or [])
        + list(drift_gate.get("blockers") or [])
    )
    # Dedupe
    seen_b: set[str] = set()
    uniq_b: list[str] = []
    for b in combined_blockers:
        if b and b not in seen_b:
            seen_b.add(b)
            uniq_b.append(b)
    desk_promote = {
        "schema_id": "tarka.desk_promote_gate/v1",
        "promote_allowed": len(uniq_b) == 0,
        "blockers": uniq_b,
        "requires": [
            "label_gated_promote",
            "mcnemar_promote_gate",
            "drift_promote_gate",
        ],
    }

    return {
        "schema_id": "tarka.shadow_promote_gate/v1",
        "vertical": "fintech",
        "blocked": blocked,
        "allowed": allowed,
        "label_gated_promote": live_promote,
        "mcnemar_promote_gate": mcnemar,
        "drift_promote_gate": drift_gate,
        "desk_promote_gate": desk_promote,
        "champion_challenger": cc_audit,
        "recipe_path": "scripts/oss/shadow_vs_primary_diff_recipe.sql",
        "smoke": "scripts/oss/shadow_promote_gate_smoke.py",
        "honesty": (
            "Demo blocked/allowed rows are kill_criteria smoke only. "
            "desk_promote_gate requires real labels + McNemar pairs + non-elevated drift."
        ),
    }


@router.get("/champion-challenger-audit")
async def champion_challenger_audit(
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Recent audit champion–challenger rows for OpsShadow (P0-CC)."""
    from decision_api.champion_challenger_audit import aggregate_champion_challenger

    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()
    out = aggregate_champion_challenger(
        [
            {
                "trace_id": str(rec.trace_id),
                "payload_snapshot": rec.payload_snapshot
                if isinstance(rec.payload_snapshot, dict)
                else {},
            }
            for rec in records
        ]
    )
    out["tenant_id"] = tenant_id
    out["audits_scanned"] = len(records)
    return out
