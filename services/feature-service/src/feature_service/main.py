import asyncio
import math
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from fraud_aggregates import AggregateStore, normalized_velocity_key_names  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402
from osint_flatten import (  # noqa: E402
    flatten_light_enrichment_response,
    flatten_osint_response,
    normalize_location_aliases,
)

# ---------- auth ----------
_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = os.environ.get("API_KEYS", "").strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    if request.url.path in {"/v1/health", "/metrics"}:
        return
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


REDIS_TAGS_URL = os.environ.get("REDIS_TAGS_HTTP", "")
ENRICHMENT_URL = os.environ.get("ENRICHMENT_URL", "")
TARKA_ASYNC_OSINT_REDIS = os.environ.get("TARKA_ASYNC_OSINT_REDIS", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Ordered keys for the normalized numeric vector
VECTOR_KEYS = [
    "amount_log",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "is_night_hours",
    "amount_bucket_micro",
    "amount_bucket_small",
    "amount_bucket_medium",
    "amount_bucket_large",
    "amount_bucket_xlarge",
    "email_risk_score",
    "phone_risk_score",
    "ip_risk_score",
    "is_disposable_email",
    "is_free_provider",
    "gravatar_exists",
    "is_proxy_ip",
    "is_hosting_ip",
    "is_voip_phone",
    "osint_composite_risk",
    "osint_ip_vpn",
    "osint_ip_proxy",
    "osint_ip_tor",
    "osint_ip_hosting",
    "osint_ip_vuln_count",
    "osint_email_disposable",
    "osint_email_breach_count",
    "osint_email_reputation",
    "osint_phone_voip",
]


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http = httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0))
    application.state.velocity_store = None
    application.state.redis_client = None
    redis_url = (os.environ.get("FEATURE_SERVICE_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()
    if redis_url:
        try:
            rc = aioredis.from_url(redis_url, decode_responses=True)
            application.state.redis_client = rc
            application.state.velocity_store = AggregateStore(rc)
        except Exception:
            application.state.velocity_store = None
    yield
    if getattr(application.state, "redis_client", None):
        await application.state.redis_client.aclose()
    await application.state.http.aclose()


app = FastAPI(
    title="Tarka Feature Service",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
if os.environ.get("TARKA_SIGNAL_PLANE_SUBAPP", "").strip() != "1":
    setup_observability(app, "feature-service")


class SnapshotRequest(BaseModel):
    tenant_id: str
    entity_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class VelocityQueryRequest(BaseModel):
    """Query Redis-backed velocity counters (same keys as decision-api aggregates)."""

    tenant_id: str
    entity_id: str
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Fields used to select sum/avg/distinct branches (e.g. amount, ip_address, device_id)",
    )


class ParityVerifyRequest(BaseModel):
    """OSS #48 — compare live Redis velocity counters to golden fixture expectations."""

    tenant_id: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, float] = Field(
        ...,
        description="Expected counter values (e.g. event_count_1h); float equality within epsilon",
    )
    epsilon: float = Field(default=0.5, ge=0.0, le=1_000_000.0)


# ---------- feature engineering helpers ----------

AMOUNT_BUCKETS = [
    (10, "micro"),
    (100, "small"),
    (1_000, "medium"),
    (10_000, "large"),
]


def _compute_amount_features(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive amount-based features from the payload."""
    features: dict[str, Any] = {}
    amount = payload.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        features["amount_log"] = round(math.log10(amount + 1), 4)
        bucket = "xlarge"
        for threshold, label in AMOUNT_BUCKETS:
            if amount < threshold:
                bucket = label
                break
        features["amount_bucket"] = bucket
    else:
        features["amount_log"] = 0.0
        features["amount_bucket"] = "micro"
    return features


def _compute_time_features() -> dict[str, Any]:
    """Derive time-based features from the current UTC time."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    dow = now.weekday()
    return {
        "hour_of_day": hour,
        "day_of_week": dow,
        "is_weekend": dow >= 5,
        "is_night_hours": hour < 6 or hour > 22,
    }


async def _fetch_enrichment(
    http: httpx.AsyncClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Call integration-ingress /v1/enrich and flatten results into features."""
    features: dict[str, Any] = {}
    body: dict[str, str] = {}
    for key in ("email", "phone", "ip"):
        if payload.get(key):
            body[key] = str(payload[key])
    if not body:
        return features

    try:
        r = await http.post(f"{ENRICHMENT_URL}/v1/enrich", json=body)
        if r.status_code != 200:
            return features
        data = r.json()
    except Exception:
        return features

    return flatten_light_enrichment_response(data)


async def _fetch_osint(
    http: httpx.AsyncClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Call integration-ingress /v1/osint and flatten key signals into features."""
    features: dict[str, Any] = {}
    body: dict[str, str] = {}
    for key in ("email", "phone", "ip", "domain"):
        if payload.get(key):
            body[key] = str(payload[key])
    if not body:
        return features

    try:
        r = await http.post(f"{ENRICHMENT_URL}/v1/osint", json=body)
        if r.status_code != 200:
            return features
        data = r.json()
    except Exception:
        return features

    features.update(flatten_osint_response(data))
    return features


async def _load_osint_from_redis(
    request: Request,
    tenant_id: str,
    entity_id: str,
) -> dict[str, Any]:
    rc = getattr(request.app.state, "redis_client", None)
    if not rc:
        return {}
    key = f"fraud:async_osint:{tenant_id}:{entity_id}"
    try:
        raw = await rc.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8")
        blob = __import__("json").loads(raw)
    except Exception:
        return {}
    if not isinstance(blob, dict):
        return {}
    osint_block = blob.get("osint")
    if isinstance(osint_block, dict):
        return flatten_osint_response(osint_block)
    if "composite_risk_score" in blob or "enrichments" in blob:
        return flatten_osint_response(blob)
    return {}


async def _compute_velocity_counters(
    request: Request,
    tenant_id: str,
    entity_id: str,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    store = getattr(request.app.state, "velocity_store", None)
    if not store:
        return None
    return await store.compute_features(tenant_id, entity_id, fields)


def _build_vector(features: dict[str, Any]) -> list[float]:
    """Build a normalized numeric vector from the feature dict."""
    vec: list[float] = []
    for key in VECTOR_KEYS:
        val = features.get(key)
        if isinstance(val, bool):
            vec.append(1.0 if val else 0.0)
        elif isinstance(val, (int, float)):
            vec.append(float(val))
        elif key.startswith("amount_bucket_"):
            suffix = key.removeprefix("amount_bucket_")
            vec.append(1.0 if features.get("amount_bucket") == suffix else 0.0)
        else:
            vec.append(0.0)
    return vec


# ---------- endpoints ----------


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo_status(request: Request):
    m = get_metrics()
    cur = m.request_count_summary()
    store = getattr(request.app.state, "velocity_store", None)
    return {
        "service": "feature-service",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 150,
        "error_budget_window_days": 30,
        "targets_note": "See docs/docs/guides/service-slos-v1.md; current from in-process HTTP counters.",
        "current": {**cur, "redis_velocity_configured": store is not None},
    }


@app.post("/v1/velocity/query")
async def velocity_query(body: VelocityQueryRequest, request: Request):
    """
    Read multi-window velocity from the shared Redis aggregate store (`fraud:agg:*`).

    Requires **REDIS_URL** or **FEATURE_SERVICE_REDIS_URL** pointing at the same Redis as decision-api
    so counters match evaluate-time aggregates. Does not write — use decision-api evaluate to record events.
    """
    store = getattr(request.app.state, "velocity_store", None)
    if not store:
        raise HTTPException(
            status_code=503,
            detail="Redis not configured — set REDIS_URL or FEATURE_SERVICE_REDIS_URL to enable velocity reads",
        )
    vel = await store.compute_features(body.tenant_id, body.entity_id, body.payload)
    return {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "velocity_counters": vel,
        "velocity_key_order": list(normalized_velocity_key_names()),
    }


@app.post("/v1/internal/parity/verify")
async def parity_verify(body: ParityVerifyRequest, request: Request):
    """
    Golden parity gate: read velocity from Redis and diff vs ``expected`` within ``epsilon``.
    Returns 200 with ``ok: true`` when all keys match; 409 when drift exceeds epsilon.
    """
    store = getattr(request.app.state, "velocity_store", None)
    if not store:
        raise HTTPException(
            status_code=503,
            detail="Redis not configured — cannot verify parity",
        )
    live = await store.compute_features(body.tenant_id, body.entity_id, body.payload)
    drift: dict[str, Any] = {}
    ok = True
    eps = float(body.epsilon)
    for key, exp in body.expected.items():
        try:
            exp_f = float(exp)
        except (TypeError, ValueError):
            drift[key] = {"expected": exp, "live": live.get(key), "error": "non_numeric_expected"}
            ok = False
            continue
        lv = live.get(key)
        try:
            lv_f = float(lv) if lv is not None else None
        except (TypeError, ValueError):
            lv_f = None
        if lv_f is None:
            drift[key] = {"expected": exp_f, "live": lv, "delta": None}
            ok = False
            continue
        delta = abs(lv_f - exp_f)
        if delta > eps:
            drift[key] = {"expected": exp_f, "live": lv_f, "delta": delta}
            ok = False
    out = {
        "ok": ok,
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "epsilon": eps,
        "checked_keys": list(body.expected.keys()),
        "drift": drift,
        "live_sample": {k: live.get(k) for k in body.expected.keys()},
    }
    if not ok:
        raise HTTPException(status_code=409, detail=out)
    return out


@app.post("/v1/snapshot")
async def snapshot(body: SnapshotRequest, request: Request):
    http: httpx.AsyncClient = request.app.state.http
    features: dict[str, Any] = dict(body.payload)
    features["event_type_feature"] = body.event_type

    features.update(_compute_amount_features(body.payload))
    features.update(_compute_time_features())

    if ENRICHMENT_URL:
        enrichment_features, osint_features = await asyncio.gather(
            _fetch_enrichment(http, body.payload),
            _fetch_osint(http, body.payload),
        )
        features.update(enrichment_features)
        features.update(osint_features)
    elif TARKA_ASYNC_OSINT_REDIS:
        redis_osint = await _load_osint_from_redis(request, body.tenant_id, body.entity_id)
        features.update(redis_osint)

    normalize_location_aliases(features)

    redis_tags: list[str] = []
    if REDIS_TAGS_URL:
        try:
            r = await http.get(
                REDIS_TAGS_URL,
                params={"tenant_id": body.tenant_id, "entity_id": body.entity_id},
            )
            if r.status_code == 200:
                redis_tags = list(r.json().get("tags", []))
        except Exception:
            pass

    vector = _build_vector(features)

    velocity_counters = await _compute_velocity_counters(request, body.tenant_id, body.entity_id, features)

    return {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "event_type": body.event_type,
        "features": features,
        "feature_vector": vector,
        "vector_keys": VECTOR_KEYS,
        "redis_tags": redis_tags,
        "velocity_counters": velocity_counters,
        "velocity_key_order": list(normalized_velocity_key_names()),
        "velocity_configured": velocity_counters is not None,
    }
