from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from decision_api.reliability_export import (  # noqa: E402
    RELIABILITY_CSV_FIELDS,
    audit_row_to_export_dict,
    reliability_bins,
    rows_to_csv,
)

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


@router.get("/reliability-bins")
async def reliability_export_bins(
    request: Request,
    tenant_id: str = Query(..., max_length=128),
    limit: int = Query(10_000, ge=1, le=_EXPORT_MAX),
    n_bins: int = Query(10, ge=2, le=50),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Equal-width reliability bins from recent audit rows (proxy labels unless y_label filled)."""
    _enforce_tenant(request, tenant_id)
    rows = await _load_audit_export_rows(session, tenant_id=tenant_id, limit=limit)
    export_rows = [audit_row_to_export_dict(r) for r in rows]
    try:
        payload = reliability_bins(export_rows, n_bins=n_bins, use_proxy_labels=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    payload["tenant_id"] = tenant_id
    payload["rows_scanned"] = len(export_rows)
    payload["csv_fields"] = list(RELIABILITY_CSV_FIELDS)
    return payload
