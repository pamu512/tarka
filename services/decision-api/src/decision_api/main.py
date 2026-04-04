import asyncio
import hashlib
import hmac
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import json as _json
import re as _re

import httpx
import nats
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.config import settings
from decision_api.currency import normalize_amount
from decision_api.db import get_session, init_db
from decision_api.fingerprint_store import fingerprint_store
from decision_api.json_rules import evaluate_json_rules, load_rules
from decision_api.models import AuditRecord
from decision_api.opa_client import evaluate_opa
from decision_api.redis_store import redis_tags
from decision_api.retention import DEFAULT_RETENTION_DAYS, retention_loop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from privacy import get_profile, mask_dict  # noqa: E402
from entity_lists import create_list_store  # noqa: E402
from decision_api.schemas import EvaluateRequest, EvaluateResponse
from decision_api.inference_build import build_inference_context, derive_recommended_action
from decision_api.shadow import evaluate_shadow, load_shadow_rules, record_observation
from decision_api.aggregates import agg_store
from decision_api.lists_api import router as lists_router, set_store, get_store as _get_list_store
from decision_api.consortium import consortium_score_delta, hash_entity_id
from decision_api.graph_intel import graph_score_delta, graph_tags_from_risk

# ---------- observability ----------
_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import setup_observability, get_metrics  # noqa: E402
from auth_rbac import setup_auth  # noqa: E402
from rate_limiter import setup_rate_limiter  # noqa: E402
from security_headers import setup_security_headers  # noqa: E402

log = logging.getLogger("decision-api")

_ANALYST_ENTITY_ID = _re.compile(r"^[a-zA-Z0-9._@:/-]{1,512}$")


def _velocity_anomaly_flags(features: dict[str, Any]) -> dict[str, Any]:
    """Heuristic flags for analyst / copilot tooling only (not a decision)."""
    ev5 = int(features.get("event_count_5m") or 0)
    ev1 = int(features.get("event_count_1h") or 0)
    ev24 = int(features.get("event_count_24h") or 0)
    flags: list[str] = []
    if ev5 >= 5:
        flags.append("burst_activity_5m")
    if ev1 >= 15:
        flags.append("high_volume_1h")
    if ev24 > 0 and ev1 > 10 and (ev1 / max(ev24, 1)) > 0.4:
        flags.append("concentrated_recent_activity_vs_24h")
    dd = int(features.get("distinct_device_id_24h") or 0)
    if dd >= 3:
        flags.append("multiple_distinct_devices_24h")
    sev = "low"
    if len(flags) >= 2:
        sev = "high"
    elif flags:
        sev = "medium"
    return {"flags": flags, "severity_hint": sev}


# ---------- websocket live feed ----------
_ws_clients: set[WebSocket] = set()

async def _broadcast_decision(data: dict) -> None:
    if not _ws_clients:
        return
    msg = _json.dumps(data, default=str)
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)

# ---------- auth ----------

_valid_api_keys: frozenset[str] | None = None

def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = settings.api_keys.strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys

async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        return
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


# ---------- lifespan ----------

@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    await redis_tags.connect()
    load_rules()
    load_shadow_rules()
    if redis_tags._client:
        agg_store.set_client(redis_tags._client)
        fingerprint_store.set_client(redis_tags._client)
    _list_store = create_list_store(
        backend=settings.list_store_backend,
        redis_url=settings.redis_url,
        file_dir=settings.list_store_file_dir,
        api_url=settings.list_store_api_url,
        api_key=settings.list_store_api_key,
    )
    await _list_store.connect()
    set_store(_list_store)
    application.state.list_store = _list_store

    application.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0, connect=2.0),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=40),
    )

    application.state.nats_nc = None
    application.state.nats_js = None
    if settings.nats_url:
        try:
            nc = await nats.connect(settings.nats_url)
            application.state.nats_nc = nc
            application.state.nats_js = nc.jetstream()
            log.info("Connected to NATS at %s", settings.nats_url)
        except Exception as e:
            log.warning("NATS connection failed (publishing disabled): %s", e)

    retention_task = None
    if DEFAULT_RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(retention_loop())

    yield

    if hasattr(application.state, 'list_store') and application.state.list_store:
        await application.state.list_store.close()
    if retention_task:
        retention_task.cancel()
    if application.state.nats_nc:
        await application.state.nats_nc.drain()
    await application.state.http.aclose()
    await redis_tags.close()


app = FastAPI(
    title="Tarka Decision API",
    version="4.0.0",
    lifespan=lifespan,
)
setup_observability(app, "decision-api")
setup_security_headers(app)
setup_auth(app)
setup_rate_limiter(app, rpm=int(os.environ.get("RATE_LIMIT_RPM", "1000")))

from decision_api.rule_api import router as rule_router  # noqa: E402
from decision_api.replay import router as replay_router  # noqa: E402
from decision_api.simulation_api import router as simulation_router  # noqa: E402
from decision_api.recommend_api import router as recommend_router  # noqa: E402
from decision_api.compliance_api import router as compliance_router  # noqa: E402
from decision_api.captcha import router as captcha_router  # noqa: E402
from decision_api.consortium_api import router as consortium_router  # noqa: E402
app.include_router(rule_router)
app.include_router(replay_router)
app.include_router(simulation_router)
app.include_router(recommend_router)
app.include_router(compliance_router)
app.include_router(captcha_router)
app.include_router(lists_router)
app.include_router(consortium_router)


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


# ---------- health ----------

@app.get("/v1/health")
async def health():
    return {"status": "ok"}


# ---------- attestation ----------

class ChallengeRequest(BaseModel):
    tenant_id: str


class VerifyRequest(BaseModel):
    nonce: str
    token: str
    provider: str


@app.post("/v1/attestation/challenge")
async def attestation_challenge(body: ChallengeRequest):
    nonce = os.urandom(32).hex()
    ttl = settings.attestation_nonce_ttl
    await redis_tags.store_nonce(nonce, ttl)
    return {"nonce": nonce, "expires_in": ttl}


@app.post("/v1/attestation/verify")
async def attestation_verify(body: VerifyRequest):
    consumed = await redis_tags.consume_nonce(body.nonce)
    if not consumed:
        raise HTTPException(400, "invalid or expired nonce")

    if body.provider == "browser_challenge":
        if not settings.attestation_hmac_secret:
            return {"valid": True, "device_integrity": "unverified_no_secret"}
        expected = hmac.new(
            settings.attestation_hmac_secret.encode(),
            body.nonce.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, body.token):
            return {"valid": False, "device_integrity": None, "reason": "hmac_mismatch"}
        return {"valid": True, "device_integrity": "browser_verified"}

    if body.provider == "play_integrity":
        # Google Play Integrity: the token is a signed JWS that must be verified
        # via Google's playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken
        # This requires GOOGLE_CLOUD_PROJECT and a service account.
        if not body.token or len(body.token) < 50:
            return {"valid": False, "device_integrity": None, "reason": "invalid_token_format"}
        log.warning("Play Integrity token received but server-side verification not configured. "
                    "Set PLAY_INTEGRITY_CREDENTIALS to enable full verification.")
        return {"valid": True, "device_integrity": "play_integrity_unverified",
                "warning": "Server-side verification pending configuration"}

    if body.provider == "app_attest":
        # Apple App Attest: token is a CBOR-encoded attestation object.
        # Requires server-side verification with Apple's attestation service.
        if not body.token or len(body.token) < 50:
            return {"valid": False, "device_integrity": None, "reason": "invalid_token_format"}
        log.warning("App Attest token received but server-side verification not configured. "
                    "Set APP_ATTEST_TEAM_ID to enable full verification.")
        return {"valid": True, "device_integrity": "app_attest_unverified",
                "warning": "Server-side verification pending configuration"}

    return {"valid": False, "device_integrity": None, "reason": "unknown_provider"}


# ---------- admin ----------

@app.post("/v1/admin/rules/reload")
async def reload_rules():
    load_rules()
    return {"ok": True}


@app.post("/v1/admin/shadow/reload")
async def reload_shadow():
    load_shadow_rules()
    return {"ok": True}


# ---------- signal tag extraction ----------

_SIGNAL_TAG_MAP = {
    "is_emulator": "sdk:emulator",
    "is_vpn": "sdk:vpn",
    "is_bot": "sdk:bot",
    "is_repackaged": "sdk:repackaged",
    "is_spoofed_location": "sdk:spoofed_location",
    "webdriver_detected": "sdk:webdriver",
    "headless_detected": "sdk:headless",
    "automation_detected": "sdk:automation",
    "timezone_geo_mismatch": "sdk:tz_geo_mismatch",
    "vpn_interface_detected": "sdk:vpn_iface",
    "mock_location_detected": "sdk:mock_location",
    "ip_is_proxy": "sdk:proxy",
    "ip_is_datacenter": "sdk:datacenter",
}


def extract_signal_tags(device_context: dict[str, Any] | None) -> list[str]:
    if not device_context:
        return []
    signals = device_context.get("signals") or {}
    tags: list[str] = []
    for key, tag in _SIGNAL_TAG_MAP.items():
        if signals.get(key) is True:
            tags.append(tag)
    return tags


def extract_captcha_tags(dc: dict | None) -> list[str]:
    """Extract CAPTCHA verification results as tags."""
    tags = []
    if not dc:
        return tags
    signals = dc.get("signals", {})
    captcha = signals.get("captcha")
    if not captcha:
        tags.append("captcha:none")
        return tags

    provider = captcha.get("provider", "unknown")
    success = captcha.get("success", False)
    score = captcha.get("score")

    if success:
        tags.append(f"captcha:{provider}:pass")
    else:
        tags.append(f"captcha:{provider}:fail")

    if score is not None:
        if score < 0.3:
            tags.append("captcha:score_low")
        elif score < 0.7:
            tags.append("captcha:score_medium")
        else:
            tags.append("captcha:score_high")

    if captcha.get("error_codes"):
        tags.append("captcha:has_errors")

    return tags


def extract_behavior_tags(device_context: dict[str, Any] | None) -> list[str]:
    if not device_context:
        return []
    behavior = device_context.get("behavior") or {}
    bot = behavior.get("bot_indicators") or {}
    tags: list[str] = []
    if bot.get("zero_mouse_movement"):
        tags.append("behavior:no_mouse")
    if bot.get("constant_typing_speed"):
        tags.append("behavior:constant_typing")
    if bot.get("no_scroll"):
        tags.append("behavior:no_scroll")
    if bot.get("suspiciously_fast"):
        tags.append("behavior:fast_typing")
    session = behavior.get("session") or {}
    if session.get("paste_count", 0) > 3:
        tags.append("behavior:heavy_paste")
    if session.get("tab_switches", 0) > 10:
        tags.append("behavior:excessive_tab_switch")
    typing = behavior.get("typing") or {}
    if typing.get("avg_inter_key_ms", 999) < 25 and typing.get("key_count", 0) > 30:
        tags.append("behavior:superhuman_typing")
    return tags


# ---------- downstream helpers ----------

async def _fetch_feature_snapshot(
    http: httpx.AsyncClient, body: EvaluateRequest, redis_tag_list: list[str]
) -> dict[str, Any]:
    if not settings.feature_service_url:
        return {
            "tenant_id": body.tenant_id,
            "entity_id": body.entity_id,
            "event_type": body.event_type.value,
            "features": dict(body.payload),
            "redis_tags": redis_tag_list,
        }
    url = settings.feature_service_url.rstrip("/") + "/v1/snapshot"
    r = await http.post(
        url,
        json={
            "tenant_id": body.tenant_id,
            "entity_id": body.entity_id,
            "event_type": body.event_type.value,
            "payload": body.payload,
        },
    )
    r.raise_for_status()
    return r.json()


async def _fetch_ml_score(
    http: httpx.AsyncClient, tenant_id: str, entity_id: str, event_type: str, features: dict[str, Any]
) -> float | None:
    if not settings.ml_scoring_url:
        return None
    url = settings.ml_scoring_url.rstrip("/") + "/v1/score"
    try:
        r = await http.post(
            url,
            json={
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_type": event_type,
                "features": features,
            },
            timeout=2.0,
        )
        if r.status_code != 200:
            return None
        return float(r.json().get("score", 0))
    except httpx.HTTPError:
        return None


async def _graph_upsert(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    trace_id: str,
    merged_tags: list[str],
) -> None:
    if not settings.graph_service_url:
        return
    base = settings.graph_service_url.rstrip("/")

    # Upsert Account node with tags
    await http.post(
        f"{base}/v1/entities",
        json={
            "tenant_id": body.tenant_id,
            "entity_type": "Account",
            "external_id": body.entity_id,
            "properties": {"last_event": body.event_type.value, "trace_id": trace_id},
            "tags": merged_tags,
        },
    )

    # Upsert Device node if device_context present
    if body.device_context:
        dc = body.device_context
        device_tags = extract_signal_tags(dc.model_dump())
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": "Device",
                "external_id": dc.device_id,
                "properties": {
                    "platform": dc.platform,
                    **{k: v for k, v in dc.signals.items() if isinstance(v, (str, bool, int, float)) or v is None},
                },
                "tags": device_tags,
            },
        )
        # Link Account -> Device
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": body.entity_id,
                "to_external_id": dc.device_id,
                "relationship": "USED",
                "properties": {"trace_id": trace_id, "event_type": body.event_type.value},
            },
        )

    # Upsert Session node if session_id present
    if body.session_id:
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": "Custom",
                "external_id": body.session_id,
                "properties": {"type": "session", "trace_id": trace_id},
                "tags": [],
            },
        )
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": body.entity_id,
                "to_external_id": body.session_id,
                "relationship": "USED",
                "properties": {"trace_id": trace_id},
            },
        )


async def _fetch_graph_risk(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
) -> dict[str, Any] | None:
    if not settings.graph_service_url:
        return None
    url = settings.graph_service_url.rstrip("/") + "/v1/analytics/entity-risk"
    try:
        r = await http.get(
            url,
            params={"tenant_id": tenant_id, "entity_id": entity_id},
            timeout=2.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except httpx.HTTPError:
        return None


def _blend_scores(rule_score: float, ml_score: float | None) -> float:
    strategy = settings.score_blend_strategy
    if ml_score is None or strategy == "rules_only":
        return max(0.0, min(100.0, rule_score))
    if strategy == "max":
        return max(0.0, min(100.0, max(rule_score, ml_score)))
    # default: average
    return max(0.0, min(100.0, (rule_score + ml_score) / 2))


# ---------- NATS decision publishing ----------

async def _publish_decision(app_state: Any, decision_data: dict) -> None:
    js = app_state.nats_js
    if not js:
        return
    tenant = decision_data.get("tenant_id", "unknown")
    etype = decision_data.get("event_type", "unknown")
    subject = f"fraud.decisions.{tenant}.{etype}"
    try:
        await js.publish(subject, _json.dumps(decision_data, default=str).encode())
    except Exception as e:
        log.warning("Failed to publish decision to NATS: %s", e)


# ---------- shadow evaluation ----------

async def _run_shadow_evaluation(
    app_state: Any,
    features: dict[str, Any],
    redis_tag_list: list[str],
    production_decision: str,
    production_score: float,
    tenant_id: str,
    trace_id: str,
) -> None:
    shadow_result = evaluate_shadow(features, redis_tag_list)
    if shadow_result is None:
        return
    shadow_decision = shadow_result["shadow_decision"]
    if shadow_decision != production_decision:
        log.warning(
            "SHADOW DIVERGENCE: production=%s shadow=%s trace_id=%s",
            production_decision,
            shadow_decision,
            trace_id,
        )
    record_observation(
        trace_id,
        {"decision": production_decision, "score": production_score},
        shadow_result,
    )
    js = app_state.nats_js
    if js:
        subject = f"fraud.shadow.{tenant_id}"
        payload = {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "production_decision": production_decision,
            **shadow_result,
        }
        try:
            await js.publish(subject, _json.dumps(payload, default=str).encode())
        except Exception as e:
            log.warning("Failed to publish shadow result to NATS: %s", e)


# ---------- main endpoint ----------

@app.post("/v1/decisions/evaluate", response_model=EvaluateResponse)
async def evaluate_decision(
    body: EvaluateRequest,
    request: Request,
    bg: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    http = _http(request)
    trace_id = uuid.uuid4()
    replay_ttl_seconds = int(os.environ.get("REPLAY_PAYLOAD_TTL_SECONDS", "300"))

    # Extract SDK signal tags
    dc_dump = body.device_context.model_dump() if body.device_context else None
    signal_tags = extract_signal_tags(dc_dump)
    signal_tags.extend(extract_behavior_tags(dc_dump))
    signal_tags.extend(extract_captcha_tags(dc_dump))
    consortium_delta = 0.0
    graph_delta = 0.0
    replay_rule_hits: list[str] = []

    # Detect payload replay at ingress using a short-lived signature cache.
    replay_signature = hashlib.sha256(
        _json.dumps(
            {
                "tenant_id": body.tenant_id,
                "event_type": body.event_type.value,
                "entity_id": body.entity_id,
                "session_id": body.session_id,
                "payload": body.payload,
                "device_id": body.device_context.device_id if body.device_context else None,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    is_replayed = await redis_tags.check_and_store_replay_signature(
        body.tenant_id, replay_signature, ttl_seconds=replay_ttl_seconds
    )
    if is_replayed:
        signal_tags.append("ingress:replay_payload")
        replay_rule_hits.append("ingress_replay_detected")

    # Record fingerprint & detect shared devices
    if body.device_context and fingerprint_store._client:
        fp_record = await fingerprint_store.record_fingerprint(
            body.tenant_id,
            body.device_context.model_dump(),
            body.entity_id,
        )
        if len(fp_record.entity_ids) > 1:
            signal_tags.append("sdk:shared_device")

    # Check whitelist/blacklist/test bypass BEFORE full evaluation
    list_check = None
    try:
        _ls = _get_list_store()
        list_check = await _ls.check(body.tenant_id, body.entity_id)
    except Exception:
        pass

    if list_check and list_check.found:
        if list_check.action == "allow":
            _wl_inf = build_inference_context([], ["whitelist_bypass"], None, 0.0, None)
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                payload_snapshot={
                    "whitelisted": True,
                    "reason": list_check.reason,
                    "inference_context": _wl_inf,
                    "recommended_action": None,
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                reasons=[f"whitelist:{list_check.reason}"],
                ml_score=None,
                inference_context=_wl_inf,
                recommended_action=None,
            )

        if list_check.action == "deny":
            _bl_inf = build_inference_context(["list:blacklist"], ["blacklist_block"], None, 100.0, None)
            _bl_rec = derive_recommended_action("deny", ["list:blacklist"], _bl_inf)
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                payload_snapshot={
                    "blacklisted": True,
                    "reason": list_check.reason,
                    "inference_context": _bl_inf,
                    "recommended_action": _bl_rec,
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                reasons=[f"blacklist:{list_check.reason}"],
                ml_score=None,
                inference_context=_bl_inf,
                recommended_action=_bl_rec,
            )

    existing_tags = await redis_tags.get_tags(body.tenant_id, body.entity_id)

    if settings.consortium_enabled:
        try:
            signal_hash = hash_entity_id(settings.consortium_secret, body.tenant_id, body.entity_id)
            consortium_data = await redis_tags.check_consortium_signal(settings.consortium_id, signal_hash)
            consortium_delta = consortium_score_delta(
                consortium_data,
                min_tenants=settings.consortium_min_tenants,
            )
            if consortium_delta > 0:
                signal_tags.append("consortium:cross_tenant_hit")
        except Exception:
            consortium_delta = 0.0

    graph_risk = await _fetch_graph_risk(http, body.tenant_id, body.entity_id)
    if graph_risk:
        graph_delta = graph_score_delta(graph_risk.get("risk_score"))
        signal_tags.extend(graph_tags_from_risk(graph_risk))

    # Feature snapshot (needed before OPA)
    snapshot = await _fetch_feature_snapshot(http, body, existing_tags)
    features: dict[str, Any] = dict(snapshot.get("features") or {})
    redis_tag_list = list(snapshot.get("redis_tags") or existing_tags)

    # Merge device signals into features so rules engine can see them
    if body.device_context:
        for k, v in body.device_context.signals.items():
            features.setdefault(k, v)

    # Normalise amount to USD if a currency is specified
    payload_currency = body.payload.get("currency")
    if payload_currency and "amount" in body.payload:
        try:
            original_amount = float(body.payload["amount"])
            normalized = await normalize_amount(original_amount, payload_currency, "USD", http)
            features["amount"] = normalized
            features["original_amount"] = original_amount
            features["original_currency"] = payload_currency
        except (TypeError, ValueError):
            pass

    # Compute real-time aggregates and inject into features
    if agg_store._client:
        agg_features = await agg_store.compute_features(body.tenant_id, body.entity_id, features)
        features.update(agg_features)
        # Record this event for future aggregate computation (uses normalised amount)
        await agg_store.record_event(
            body.tenant_id, body.entity_id, str(trace_id), features
        )

    # Run rules + OPA + ML in parallel (OPA and ML don't need each other)
    rule_hits, rule_tags, score_delta = evaluate_json_rules(features, redis_tag_list)

    opa_coro = evaluate_opa(http, settings.opa_url, {"snapshot": snapshot})
    ml_coro = _fetch_ml_score(http, body.tenant_id, body.entity_id, body.event_type.value, features)
    opa_result, ml_score = await asyncio.gather(opa_coro, ml_coro, return_exceptions=False)

    if opa_result and isinstance(opa_result, dict):
        rule_hits.extend(str(x) for x in opa_result.get("rule_hits", []))
        rule_tags.extend(str(t) for t in opa_result.get("tags", []))
        score_delta += float(opa_result.get("score_delta", 0))

    all_new_tags = rule_tags + signal_tags
    if consortium_delta > 0:
        rule_hits.append("consortium_shared_signal")
    if graph_delta > 0:
        rule_hits.append("graph_network_risk")
    replay_delta = 20.0 if is_replayed else 0.0
    base_score = 10.0 + score_delta + consortium_delta + graph_delta + replay_delta
    final_score = _blend_scores(base_score, ml_score if isinstance(ml_score, float) else None)

    merged_tags = await redis_tags.merge_tags(body.tenant_id, body.entity_id, all_new_tags)
    await redis_tags.set_cached_score(body.tenant_id, body.entity_id, final_score)

    combined_rule_hits = rule_hits + replay_rule_hits

    if final_score >= settings.deny_threshold:
        decision = "deny"
    elif final_score >= settings.review_threshold:
        decision = "review"
    else:
        decision = "allow"

    reasons: list[str] = []
    if combined_rule_hits:
        reasons.append(f"rules:{','.join(combined_rule_hits)}")
    if signal_tags:
        reasons.append(f"signals:{','.join(signal_tags)}")
    if ml_score is not None and isinstance(ml_score, float):
        reasons.append(f"ml:{ml_score:.2f}")

    inf_ctx = build_inference_context(
        signal_tags,
        combined_rule_hits,
        ml_score if isinstance(ml_score, float) else None,
        final_score,
        features,
    )
    recommended_action = derive_recommended_action(decision, signal_tags, inf_ctx)

    # Apply region-aware PII masking before storage
    region = getattr(body, "region", settings.default_region) or settings.default_region
    privacy_profile = get_profile(region)
    raw_snapshot = {"payload": body.payload, "metadata": body.metadata}
    if privacy_profile.mask_pii_in_logs or privacy_profile.pseudonymize_at_rest:
        stored_snapshot = mask_dict(raw_snapshot, privacy_profile)
    else:
        stored_snapshot = raw_snapshot

    audit = AuditRecord(
        trace_id=trace_id,
        tenant_id=body.tenant_id,
        entity_id=body.entity_id,
        event_type=body.event_type.value,
        decision=decision,
        score=final_score,
        tags=merged_tags,
        rule_hits=combined_rule_hits,
        payload_snapshot={
            **stored_snapshot,
            "inference_context": inf_ctx,
            "recommended_action": recommended_action,
        },
    )
    session.add(audit)
    await session.commit()

    bg.add_task(_graph_upsert, http, body, str(trace_id), merged_tags)

    try:
        m = get_metrics()
        m.inc(f"fraud_decisions_{decision}_total")
        m.inc("fraud_evaluations_total")
        if signal_tags:
            for st in signal_tags:
                m.inc(f"fraud_signal_tag_{st}_total")
    except Exception:
        pass

    response = EvaluateResponse(
        trace_id=trace_id,
        decision=decision,
        score=final_score,
        tags=merged_tags,
        rule_hits=combined_rule_hits,
        reasons=reasons,
        ml_score=ml_score if isinstance(ml_score, float) else None,
        inference_context=inf_ctx,
        recommended_action=recommended_action,
    )

    bg.add_task(_broadcast_decision, {
        "trace_id": str(trace_id), "tenant_id": body.tenant_id,
        "entity_id": body.entity_id, "event_type": body.event_type.value,
        "decision": decision, "score": final_score, "tags": merged_tags,
    })

    bg.add_task(_publish_decision, request.app.state, {
        "trace_id": str(trace_id),
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "event_type": body.event_type.value,
        "decision": decision,
        "score": final_score,
        "tags": merged_tags,
        "rule_hits": combined_rule_hits,
        "signal_tags": signal_tags,
        "ml_score": ml_score if isinstance(ml_score, float) else None,
        "payload": body.payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    bg.add_task(
        _run_shadow_evaluation,
        request.app.state,
        features,
        redis_tag_list,
        decision,
        final_score,
        body.tenant_id,
        str(trace_id),
    )

    # Test bypass: run full evaluation but override decision to allow
    if list_check and list_check.found and list_check.list_type == "test_bypass":
        _tb_hits = combined_rule_hits + ["test_bypass"]
        _tb_inf = build_inference_context(
            signal_tags,
            _tb_hits,
            ml_score if isinstance(ml_score, float) else None,
            final_score,
            features,
        )
        response = EvaluateResponse(
            trace_id=trace_id,
            decision="allow",
            score=final_score,
            tags=merged_tags + ["list:test_bypass"],
            rule_hits=_tb_hits,
            reasons=reasons + [f"test_bypass:{list_check.reason}"],
            ml_score=ml_score if isinstance(ml_score, float) else None,
            inference_context=_tb_inf,
            recommended_action=derive_recommended_action("allow", signal_tags, _tb_inf),
        )

    return response


# ---------- websocket ----------

@app.websocket("/v1/decisions/ws")
async def ws_decision_feed(ws: WebSocket):
    """Live stream of fraud decisions for dashboards."""
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(ws)


# ---------- rule builder UI ----------
from pathlib import Path as _Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = _Path(__file__).resolve().parent.parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/rules-ui", include_in_schema=False)
    async def rules_ui():
        return FileResponse(_STATIC_DIR / "rule-builder.html")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_ui():
        return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/v1/audit/{trace_id}")
async def get_audit(
    trace_id: UUID,
    tenant_id: str = Query(..., description="Must match the audit row tenant_id"),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(AuditRecord).where(AuditRecord.trace_id == trace_id))
    row = result.scalar_one_or_none()
    if not row or str(row.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="not found")
    snap = row.payload_snapshot or {}
    return {
        "trace_id": str(row.trace_id),
        "tenant_id": row.tenant_id,
        "entity_id": row.entity_id,
        "event_type": row.event_type,
        "decision": row.decision,
        "score": row.score,
        "tags": row.tags,
        "rule_hits": row.rule_hits,
        "inference_context": snap.get("inference_context"),
        "recommended_action": snap.get("recommended_action"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/v1/analyst/entity-velocity")
async def analyst_entity_velocity(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    entity_id: str = Query(..., min_length=1, max_length=512),
):
    """Redis-backed event counts + velocity slice of inference_context for investigations (read-only)."""
    eid = str(entity_id).strip()
    tid = str(tenant_id).strip()
    if not _ANALYST_ENTITY_ID.match(eid):
        raise HTTPException(status_code=400, detail="invalid entity_id")
    try:
        raw_features = await agg_store.compute_features(tid, eid, {})
    except Exception as exc:
        log.warning("entity-velocity aggregates failed: %s", exc)
        raw_features = {f"event_count_{w}": 0 for w in ("5m", "1h", "24h", "7d")}
    inf = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=0.0,
        features=raw_features,
    )
    vel_keys = ("event_count_5m", "event_count_1h", "event_count_24h", "event_count_7d")
    agg_slice = {k: raw_features.get(k, 0) for k in vel_keys}
    for k, v in sorted(raw_features.items()):
        if k.startswith("distinct_"):
            agg_slice[k] = v
    return {
        "entity_id": eid,
        "tenant_id": tid,
        "aggregate_features": agg_slice,
        "inference_velocity": {
            "velocity_events_5m": inf["velocity_events_5m"],
            "velocity_events_1h": inf["velocity_events_1h"],
            "velocity_events_24h": inf["velocity_events_24h"],
            "impossible_travel_risk": inf["impossible_travel_risk"],
            "colocation_risk": inf["colocation_risk"],
            "driver_reasons": [
                d
                for d in inf["driver_reasons"]
                if any(
                    x in d
                    for x in ("velocity", "travel", "device", "entity", "ml_score")
                )
            ],
        },
        "anomaly_flags": _velocity_anomaly_flags(raw_features),
    }
