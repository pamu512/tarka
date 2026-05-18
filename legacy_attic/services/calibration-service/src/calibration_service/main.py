import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
import contextlib

from auth import require_api_key  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402


def _data_dir() -> Path:
    base = (os.environ.get("CALIBRATION_SERVICE_DATA_DIR") or "").strip()
    p = Path(base) if base else (Path(__file__).resolve().parents[3] / "data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _profiles_path() -> Path:
    return _data_dir() / "profiles.json"


def _snapshots_path() -> Path:
    return _data_dir() / "snapshots.jsonl"


def _load_profiles() -> dict[str, Any]:
    p = _profiles_path()
    if not p.is_file():
        return {"profiles": {}, "active": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"profiles": {}, "active": {}}


def _save_profiles(data: dict[str, Any]) -> None:
    _profiles_path().write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class CalibrationBand(BaseModel):
    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)
    adjustment: float = Field(ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "CalibrationBand":
        if self.max < self.min:
            raise ValueError("max must be >= min")
        return self


class CalibrationProfileIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    expected_calibration_version: int = Field(default=1, ge=1)
    fallback: bool = False
    bands: list[CalibrationBand] = Field(min_length=1)


class CalibrationSnapshotIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(default="default", max_length=64)
    sample_count: int = Field(ge=1, le=1_000_000)
    integrity_histogram: dict[str, int] = Field(default_factory=dict)
    mean_integrity: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_final_score: float | None = Field(default=None, ge=0.0, le=100.0)
    notes: str | None = Field(default=None, max_length=512)


class CalibrationScoreRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(default="default", max_length=64)
    baseline_confidence: float = Field(ge=0.0, le=1.0)
    features: dict[str, Any] = Field(default_factory=dict)


def _profile_key(tenant_id: str, profile_id: str) -> str:
    return f"{tenant_id}:{profile_id}"


def _active_profile_for(tenant_id: str, profile_id: str) -> dict[str, Any]:
    data = _load_profiles()
    key = _profile_key(tenant_id, profile_id)
    active = data.get("active", {}).get(key)
    profiles = data.get("profiles", {}).get(key, [])
    if active is None:
        if profiles:
            return profiles[-1]
        raise HTTPException(404, f"profile not found for tenant={tenant_id} profile={profile_id}")
    for p in profiles:
        if int(p.get("version", 0)) == int(active):
            return p
    raise HTTPException(
        404, f"active profile version missing for tenant={tenant_id} profile={profile_id}"
    )


def _append_snapshot(row: dict[str, Any]) -> str:
    p = _snapshots_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]


def _drift_hint(tenant_id: str, profile_id: str) -> dict[str, Any]:
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
            if row.get("tenant_id") == tenant_id and row.get("profile_id") == profile_id:
                latest = row
                break
    if not latest:
        return {"drift_score": None, "hint": "no_snapshots"}
    mean_integrity = latest.get("mean_integrity")
    if mean_integrity is None:
        return {"drift_score": None, "hint": "no_mean_integrity"}
    drift = abs(float(mean_integrity) - 0.5)
    hint = "ok"
    if drift >= 0.25:
        hint = "elevated_bin_shift_review_calibration"
    elif drift >= 0.15:
        hint = "moderate_drift_monitor"
    return {"drift_score": round(drift, 4), "hint": hint, "latest_ts": latest.get("ts")}


app = FastAPI(
    title="Tarka Calibration Service",
    version="1.0.0",
    dependencies=[Depends(require_api_key)],
)
if os.environ.get("TARKA_SIGNAL_PLANE_SUBAPP", "").strip() != "1":
    setup_observability(app, "calibration-service")


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo():
    return {
        "service": "calibration-service",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 120,
        "error_budget_window_days": 30,
        "current": get_metrics().request_count_summary(),
    }


@app.post("/v1/profiles", status_code=201)
async def publish_profile(body: CalibrationProfileIn):
    data = _load_profiles()
    key = _profile_key(body.tenant_id, body.profile_id)
    bucket = list(data.get("profiles", {}).get(key, []))
    bucket = [p for p in bucket if int(p.get("version", 0)) != body.version]
    payload = {
        "tenant_id": body.tenant_id,
        "profile_id": body.profile_id,
        "version": body.version,
        "expected_calibration_version": body.expected_calibration_version,
        "fallback": bool(body.fallback),
        "bands": [b.model_dump() for b in body.bands],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    bucket.append(payload)
    bucket.sort(key=lambda x: int(x.get("version", 0)))
    data.setdefault("profiles", {})[key] = bucket
    data.setdefault("active", {}).setdefault(key, body.version)
    _save_profiles(data)
    return payload


@app.get("/v1/profiles/{tenant_id}/{profile_id}")
async def get_profile(tenant_id: str, profile_id: str):
    return _active_profile_for(tenant_id, profile_id)


@app.post("/v1/profiles/{tenant_id}/{profile_id}/activate")
async def activate_profile(tenant_id: str, profile_id: str, body: dict[str, int]):
    version = int(body.get("version") or 0)
    if version <= 0:
        raise HTTPException(422, "version must be >= 1")
    data = _load_profiles()
    key = _profile_key(tenant_id, profile_id)
    bucket = data.get("profiles", {}).get(key, [])
    if not any(int(p.get("version", 0)) == version for p in bucket):
        raise HTTPException(404, f"profile version {version} not found")
    data.setdefault("active", {})[key] = version
    _save_profiles(data)
    return {"ok": True, "tenant_id": tenant_id, "profile_id": profile_id, "version": version}


@app.post("/v1/snapshots", status_code=201)
async def append_snapshot(body: CalibrationSnapshotIn):
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "tenant_id": body.tenant_id,
        "profile_id": body.profile_id,
        "sample_count": body.sample_count,
        "integrity_histogram": body.integrity_histogram,
        "mean_integrity": body.mean_integrity,
        "mean_final_score": body.mean_final_score,
        "notes": body.notes,
    }
    sid = _append_snapshot(row)
    return {"ok": True, "snapshot_id": sid}


@app.get("/v1/drift")
async def drift(tenant_id: str, profile_id: str = "default"):
    return {
        "tenant_id": tenant_id,
        "profile_id": profile_id,
        **_drift_hint(tenant_id, profile_id),
    }


@app.get("/v1/reliability/export")
async def reliability_export(tenant_id: str, profile_id: str = "default"):
    rows: list[dict[str, Any]] = []
    sp = _snapshots_path()
    if sp.is_file():
        for line in sp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("tenant_id") == tenant_id and row.get("profile_id") == profile_id:
                rows.append(row)
    return {
        "tenant_id": tenant_id,
        "profile_id": profile_id,
        "snapshot_count": len(rows),
        "snapshots": rows[-200:],
    }


def _resolve_band_adjustment(confidence: float, bands: list[dict[str, Any]]) -> float:
    for b in bands:
        try:
            mn = float(b.get("min", 0.0))
            mx = float(b.get("max", 1.0))
            adj = float(b.get("adjustment", 0.0))
        except (TypeError, ValueError):
            continue
        if mn <= confidence <= mx:
            return adj
    return 0.0


@app.post("/v1/score")
async def score(body: CalibrationScoreRequest, request: Request):
    try:
        profile = _active_profile_for(body.tenant_id, body.profile_id)
    except HTTPException:
        profile = {
            "profile_id": "default",
            "version": 1,
            "expected_calibration_version": 1,
            "fallback": True,
            "bands": [{"min": 0.0, "max": 1.0, "adjustment": 0.0}],
        }
    baseline = float(body.baseline_confidence)
    band_adj = _resolve_band_adjustment(baseline, profile.get("bands", []))
    velocity_penalty = 0.0
    try:
        ev1h = float(body.features.get("event_count_1h") or 0)
    except (TypeError, ValueError):
        ev1h = 0.0
    if ev1h >= 25:
        velocity_penalty = -0.05
    elif ev1h >= 10:
        velocity_penalty = -0.02
    drift = _drift_hint(body.tenant_id, body.profile_id)
    drift_penalty = 0.0
    ds = drift.get("drift_score")
    if isinstance(ds, (int, float)):
        drift_penalty = -min(0.15, float(ds) * 0.25)
    delta = band_adj + velocity_penalty + drift_penalty
    calibrated = _clamp01(baseline + delta)
    with contextlib.suppress(Exception):
        get_metrics().inc("tarka_calibration_scores_total")
    return {
        "baseline_confidence": round(baseline, 4),
        "calibrated_confidence": round(calibrated, 4),
        "delta": round(calibrated - baseline, 4),
        "profile_id": profile.get("profile_id", "default"),
        "profile_version": int(profile.get("version", 1)),
        "expected_calibration_version": int(profile.get("expected_calibration_version", 1)),
        "drift": drift,
        "used_fallback_profile": bool(profile.get("fallback", False)),
        "trace_meta": {
            "remote": request.client.host if request.client else "",
            "velocity_penalty": round(velocity_penalty, 4),
            "drift_penalty": round(drift_penalty, 4),
            "band_adjustment": round(band_adj, 4),
        },
    }
