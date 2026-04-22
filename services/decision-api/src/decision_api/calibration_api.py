from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from decision_api.config import settings

"""Stretch: lightweight calibration snapshots and drift hints (file-backed; not full reliability diagrams)."""
router = APIRouter(prefix="/v1/calibration", tags=["calibration"])


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
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in profile.strip())[:120] or "default"


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
    _references_path().write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


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
    return {"ok": True, "id": hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]}


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
        return {"tenant_id": tenant_id, "profile": safe_profile, "drift_score": None, "hint": "empty_histograms"}
    total_r = sum(int(ref_hist.get(k, 0)) for k in keys)
    total_c = sum(int(cur_hist.get(k, 0)) for k in keys)
    if total_r <= 0 or total_c <= 0:
        return {"tenant_id": tenant_id, "profile": safe_profile, "drift_score": None, "hint": "insufficient_mass"}
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
    return compute_drift_for_tenant(tenant_id, profile)


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
