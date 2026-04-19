import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from auth import require_api_key  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402


def _trusted_places_path() -> Path:
    base = (os.environ.get("LOCATION_SERVICE_DATA_DIR") or "").strip()
    root = Path(base) if base else (Path(__file__).resolve().parents[3] / "data")
    root.mkdir(parents=True, exist_ok=True)
    return root / "trusted_places.json"


def _load_trusted_places() -> dict[str, list[dict[str, Any]]]:
    p = _trusted_places_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except json.JSONDecodeError:
        return {}


_SAFE_TRUSTED_PLACE_KINDS = frozenset({"home", "work", "travel", "other"})


def _coerce_bounded_float(value: Any, *, min_v: float, max_v: float) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out < min_v or out > max_v:
        return None
    return out


def _sanitize_place_entry(place: dict[str, Any]) -> dict[str, Any]:
    """
    Persist only minimal geometric metadata needed by scoring.

    This intentionally drops all free-form strings to reduce accidental clear-text
    storage of PII in trusted-place snapshots.
    """
    lat = _coerce_bounded_float(place.get("lat"), min_v=-90.0, max_v=90.0)
    lon = _coerce_bounded_float(place.get("lon"), min_v=-180.0, max_v=180.0)
    radius_km = _coerce_bounded_float(place.get("radius_km"), min_v=0.05, max_v=5000.0)
    if lat is None or lon is None or radius_km is None:
        return {}
    kind_raw = str(place.get("kind") or "other").strip().lower()
    kind = kind_raw if kind_raw in _SAFE_TRUSTED_PLACE_KINDS else "other"
    out: dict[str, Any] = {
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "radius_km": round(radius_km, 3),
        "kind": kind,
    }
    accuracy_m = _coerce_bounded_float(place.get("accuracy_m"), min_v=0.0, max_v=100000.0)
    if accuracy_m is not None:
        out["accuracy_m"] = round(accuracy_m, 2)
    return out


def _save_trusted_places(data: dict[str, list[dict[str, Any]]]) -> None:
    sanitized: dict[str, list[dict[str, Any]]] = {
        k: [clean for p in v if isinstance(p, dict) and (clean := _sanitize_place_entry(dict(p)))] for k, v in data.items()
    }
    _trusted_places_path().write_text(
        json.dumps(sanitized, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(max(1e-12, 1 - a)))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    ts: float | None = None
    source: str | None = None


class LocationResolveRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    device_geo: GeoPoint | None = None
    ip_geo: GeoPoint | None = None
    timezone: str | None = None
    ip_timezone: str | None = None


class LocationEvaluateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    session_id: str | None = None
    current: GeoPoint | None = None
    previous: GeoPoint | None = None
    trusted_places: list[dict[str, Any]] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)


class TrustedPlacesRequest(BaseModel):
    places: list[dict[str, Any]] = Field(default_factory=list)


app = FastAPI(
    title="Tarka Location Service",
    version="1.0.0",
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "location-service")


def _trusted_key(tenant_id: str, entity_id: str) -> str:
    return f"{tenant_id}:{entity_id}"


def _resolve_location(req: LocationResolveRequest) -> tuple[GeoPoint, float, list[str], list[str], float | None]:
    provenance: list[str] = []
    tags: list[str] = []
    confidence = 0.0
    distance_km: float | None = None

    if req.device_geo:
        resolved = req.device_geo
        provenance.append("device_geo")
        confidence = 0.8
    elif req.ip_geo:
        resolved = req.ip_geo
        provenance.append("ip_geo")
        confidence = 0.55
    else:
        resolved = GeoPoint(lat=0.0, lon=0.0, source="none")
        confidence = 0.0
        tags.append("location:missing")

    if req.device_geo and req.ip_geo:
        distance_km = _haversine_km(req.device_geo.lat, req.device_geo.lon, req.ip_geo.lat, req.ip_geo.lon)
        if distance_km > 500:
            tags.append("sdk:geo_ip_mismatch")
            confidence = max(0.0, confidence - 0.25)
        elif distance_km > 120:
            tags.append("location:device_ip_delta_elevated")
            confidence = max(0.0, confidence - 0.1)

    if req.timezone and req.ip_timezone:
        t1 = req.timezone.lower()
        t2 = req.ip_timezone.lower()
        if t1 != t2 and t1.split("/")[-1] not in t2 and t2.split("/")[-1] not in t1:
            tags.append("sdk:geo_tz_mismatch")
            confidence = max(0.0, confidence - 0.1)

    return resolved, _clamp01(confidence), provenance, tags, distance_km


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo():
    return {
        "service": "location-service",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 120,
        "error_budget_window_days": 30,
        "current": get_metrics().request_count_summary(),
    }


@app.post("/v1/resolve")
async def resolve(req: LocationResolveRequest):
    resolved, confidence, provenance, tags, distance_km = _resolve_location(req)
    return {
        "resolved": resolved.model_dump(),
        "confidence": confidence,
        "provenance": provenance,
        "tags": tags,
        "device_ip_distance_km": round(distance_km, 3) if distance_km is not None else None,
    }


def _copresence_risk(features: dict[str, Any]) -> float:
    try:
        distinct_sessions = float(features.get("distinct_session_id_24h") or 0)
    except (TypeError, ValueError):
        distinct_sessions = 0.0
    if distinct_sessions <= 1:
        return 0.0
    return _clamp01(0.25 + min(0.6, 0.1 * distinct_sessions))


def _impossible_travel_risk(current: GeoPoint | None, previous: GeoPoint | None) -> tuple[float, float | None]:
    if not current or not previous or current.ts is None or previous.ts is None:
        return 0.0, None
    if current.ts <= previous.ts:
        return 0.0, None
    dt_h = max((current.ts - previous.ts) / 3600.0, 1e-6)
    dist = _haversine_km(current.lat, current.lon, previous.lat, previous.lon)
    speed = dist / dt_h
    if speed > 900:
        return 0.95, speed
    if speed > 800:
        return 0.75, speed
    if speed > 250:
        return 0.45, speed
    return 0.0, speed


@app.post("/v1/evaluate")
async def evaluate(req: LocationEvaluateRequest):
    resolved, confidence, provenance, tags, _ = _resolve_location(
        LocationResolveRequest(
            tenant_id=req.tenant_id,
            device_geo=req.current,
            ip_geo=req.previous if req.current is None else None,
            timezone=str(req.features.get("timezone") or "") or None,
            ip_timezone=str(req.features.get("ip_geo_timezone") or "") or None,
        )
    )

    copresence = _copresence_risk(req.features)
    travel_risk, speed = _impossible_travel_risk(req.current, req.previous)
    if travel_risk >= 0.45:
        tags.append("velocity_and_geo_suggest_impossible_travel")

    trusted = req.trusted_places
    if not trusted:
        trusted = _load_trusted_places().get(_trusted_key(req.tenant_id, req.entity_id), [])

    trusted_hit = False
    if trusted and req.current:
        for tp in trusted:
            try:
                la = float(tp.get("lat"))
                lo = float(tp.get("lon"))
                rk = float(tp.get("radius_km"))
            except (TypeError, ValueError):
                continue
            if _haversine_km(req.current.lat, req.current.lon, la, lo) <= max(0.1, rk):
                trusted_hit = True
                break
    if trusted_hit:
        confidence = _clamp01(confidence + 0.1)
        travel_risk = max(0.0, travel_risk - 0.25)
        tags.append("location:trusted_place_hit")

    return {
        "location_confidence": round(confidence, 4),
        "copresence_risk": round(copresence, 4),
        "impossible_travel_risk": round(travel_risk, 4),
        "tags": tags,
        "trace": {
            "provenance": provenance,
            "resolved_source": resolved.source or "derived",
            "estimated_speed_kmh": round(speed, 3) if speed is not None else None,
            "trusted_places_checked": len(trusted),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@app.put("/v1/trusted-places/{tenant_id}/{entity_id}")
async def put_trusted_places(tenant_id: str, entity_id: str, body: TrustedPlacesRequest):
    data = _load_trusted_places()
    data[_trusted_key(tenant_id, entity_id)] = list(body.places)
    _save_trusted_places(data)
    return {"ok": True, "tenant_id": tenant_id, "entity_id": entity_id, "count": len(body.places)}


@app.get("/v1/trusted-places/{tenant_id}/{entity_id}")
async def get_trusted_places(tenant_id: str, entity_id: str):
    data = _load_trusted_places()
    return {"places": data.get(_trusted_key(tenant_id, entity_id), [])}
