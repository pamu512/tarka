import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.adapters import ADAPTERS, verify
from integration_ingress.config import settings
from integration_ingress.db import get_session, init_db
from integration_ingress.enrichment import enrich_email, enrich_ip, enrich_phone
from integration_ingress.integration_catalog import PROVIDER_CATALOG, get_provider, list_categories
from integration_ingress.kms_adapter import AwsKMSAdapter, AzureKMSAdapter, GcpKMSAdapter, LocalKMSAdapter
from integration_ingress.models import (
    IntegrationConnection,
    IntegrationOperation,
    KMSRotationFailure,
    KMSRotationJob,
    WebhookInbox,
)
from integration_ingress.osint import OsintConfig, full_osint_enrichment
from integration_ingress.vault import InMemoryVault

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from audit_trail import AuditTrail, create_audit_model  # noqa: E402
from auth_rbac import get_current_user, require_role, setup_auth  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402
from privacy import get_profile  # noqa: E402

logger = logging.getLogger(__name__)

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
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


_osint_cfg = OsintConfig(
    abuseipdb_key=settings.abuseipdb_key,
    greynoise_key=settings.greynoise_key,
    emailrep_key=settings.emailrep_key,
    numverify_key=settings.numverify_key,
    ipinfo_token=settings.ipinfo_token,
)
_integration_requests: list[dict[str, Any]] = []
_kms_metrics: dict[str, float | int] = {
    "encrypt_calls": 0,
    "decrypt_calls": 0,
    "rotation_jobs": 0,
    "rotation_failures": 0,
}
_keyring: dict[str, str] = {}
if settings.kms_keyring_json.strip():
    try:
        parsed = json.loads(settings.kms_keyring_json)
        if isinstance(parsed, dict):
            _keyring = {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        _keyring = {}
if settings.kms_active_key_id not in _keyring:
    _keyring[settings.kms_active_key_id] = settings.integration_vault_key

if settings.kms_provider == "aws":
    _kms = AwsKMSAdapter(region_name=settings.aws_kms_region, endpoint_url=settings.aws_kms_endpoint_url)
    _active_key_ref = settings.kms_active_key_id
elif settings.kms_provider == "gcp":
    _kms = GcpKMSAdapter()
    _active_key_ref = settings.gcp_kms_key_resource or settings.kms_active_key_id
elif settings.kms_provider == "azure":
    _kms = AzureKMSAdapter(
        vault_url=settings.azure_key_vault_url,
        key_name=settings.azure_kms_key_name,
        credential_mode=settings.azure_kms_credential_mode,
    )
    _active_key_ref = settings.kms_active_key_id or settings.azure_kms_key_name
else:
    _kms = LocalKMSAdapter(_keyring)
    _active_key_ref = settings.kms_active_key_id

_vault = InMemoryVault(
    kms=_kms,
    active_key_id=_active_key_ref,
)

_PROVIDER_SANDBOX_PROBES: dict[str, dict[str, str]] = {
    "stripe_radar": {"path_hint": "radar", "host_hint": "stripe.com"},
    "jira": {"path_hint": "jira", "host_hint": "atlassian.com"},
    "salesforce": {"path_hint": "salesforce", "host_hint": "salesforce.com"},
    "complyadvantage": {"path_hint": "comply", "host_hint": "complyadvantage.com"},
    "opensanctions": {"path_hint": "sanction", "host_hint": "opensanctions.org"},
}

CONNECTOR_QUALITY_VERSION = 1


def _latency_component_ms(latency_ms: float) -> float:
    """0–100: lower latency scores higher."""
    if latency_ms <= 0:
        return 50.0
    # Full credit under 300ms, decay to 0 by 2500ms
    if latency_ms <= 300:
        return 100.0
    if latency_ms >= 2500:
        return 0.0
    return round(100.0 * (1.0 - (latency_ms - 300) / 2200.0), 1)


def _connector_quality_v1_from_probe(
    provider: dict[str, Any],
    *,
    probe_ok: bool,
    probe_latency_ms: float,
    probe_error: str,
) -> dict[str, Any]:
    """Heuristic v1 when tenant credentials are not evaluated (preflight / public doc probes)."""
    reach = 100.0 if probe_ok else 0.0
    lat = _latency_component_ms(probe_latency_ms) if probe_ok else 0.0
    sem = 100.0
    err = (probe_error or "").strip()
    if err in {"host_hint_mismatch", "sandbox_semantic_check_failed"}:
        sem = 40.0
    score = round((reach * 0.45) + (lat * 0.25) + (sem * 0.3), 1)
    return {
        "version": CONNECTOR_QUALITY_VERSION,
        "score": min(100.0, score),
        "components": {
            "doc_reachability": reach,
            "latency_shape": lat,
            "sandbox_semantics": sem,
        },
        "probe_error": err or None,
    }


def _connector_quality_v1_installed(
    provider: dict[str, Any],
    last: dict[str, Any],
) -> dict[str, Any]:
    """v1 score for a configured integration using last connectivity test + catalog metadata."""
    check_status = str(last.get("status", "unknown")).lower()
    live_probe = last.get("live_probe") if isinstance(last.get("live_probe"), dict) else {}
    probe_ok = bool(live_probe.get("ok"))
    probe_latency_ms = float(live_probe.get("latency_ms") or last.get("latency_ms") or 0.0)
    probe_error = str(live_probe.get("error") or "")
    missing_fields = last.get("missing_fields") or []
    if not isinstance(missing_fields, list):
        missing_fields = []

    auth_ok = check_status == "pass"
    req_fields = provider.get("required_config_fields") or []
    req_n = len(req_fields) if isinstance(req_fields, list) else 0
    missing_n = len(missing_fields)
    config_pct = _config_completeness(req_n, missing_n)

    reach = 100.0 if auth_ok else (35.0 if check_status == "fail" else 50.0)
    probe_reach = 100.0 if probe_ok else 0.0
    lat = _latency_component_ms(probe_latency_ms) if probe_ok else 0.0
    sem = 100.0
    if probe_error in {"host_hint_mismatch", "sandbox_semantic_check_failed"}:
        sem = 45.0

    score = round(
        (reach * 0.35) + (probe_reach * 0.25) + (lat * 0.15) + (sem * 0.15) + (config_pct * 0.1),
        1,
    )
    return {
        "version": CONNECTOR_QUALITY_VERSION,
        "score": min(100.0, score),
        "components": {
            "auth_material": reach,
            "live_probe": probe_reach,
            "latency_shape": lat,
            "sandbox_semantics": sem,
            "config_completeness_pct": config_pct,
        },
        "probe_error": probe_error or None,
    }


def _validate_kms_config() -> list[str]:
    issues: list[str] = []
    provider = settings.kms_provider.lower().strip()
    if provider == "aws":
        if not settings.aws_kms_region:
            issues.append("AWS_KMS_REGION is required for aws provider")
        if not settings.kms_active_key_id:
            issues.append("KMS_ACTIVE_KEY_ID is required for aws provider")
    elif provider == "gcp":
        if not settings.gcp_kms_key_resource:
            issues.append("GCP_KMS_KEY_RESOURCE is required for gcp provider")
        elif "/cryptoKeys/" not in settings.gcp_kms_key_resource:
            issues.append("GCP_KMS_KEY_RESOURCE must be full cryptoKey resource path")
    elif provider == "azure":
        if not settings.azure_key_vault_url:
            issues.append("AZURE_KEY_VAULT_URL is required for azure provider")
        if not settings.azure_kms_key_name:
            issues.append("AZURE_KMS_KEY_NAME is required for azure provider")
    return issues


from integration_ingress.db import Base  # noqa: E402

AuditRecord = create_audit_model(Base)
_trail = AuditTrail(AuditRecord)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    await init_db()
    if settings.kms_startup_self_check:
        issues = _validate_kms_config()
        if not issues:
            probe = b"tarka-startup-kms-check"
            try:
                c = _kms.encrypt(probe, key_id=_vault.active_key_id)
                p = _kms.decrypt(c, key_id=_vault.active_key_id)
                if p != probe:
                    raise RuntimeError("kms self-check decrypt mismatch")
            except Exception as exc:
                raise RuntimeError(f"kms startup self-check failed: {exc}") from exc
    rotation_task: asyncio.Task | None = None

    async def _rotation_loop():
        while True:
            try:
                await asyncio.sleep(max(60, settings.kms_rotation_interval_seconds))
                async for session in get_session():
                    new_key_id = f"v{int(time.time())}"
                    await _vault.rotate_all_secrets(
                        session,
                        new_key_id=new_key_id,
                        new_key_material=f"{settings.integration_vault_key}:{new_key_id}",
                    )
                    await session.commit()
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    if settings.kms_rotation_enabled:
        rotation_task = asyncio.create_task(_rotation_loop())
    yield
    if rotation_task:
        rotation_task.cancel()
    await application.state.http.aclose()


app = FastAPI(
    title="Tarka Integration Ingress",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "integration-ingress")
setup_auth(app)


class KycVerifyRequest(BaseModel):
    tenant_id: str
    subject_id: str
    adapter: str
    document: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class EnrichRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    ip: str | None = None


class OsintRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    ip: str | None = None
    domain: str | None = None


class IntegrationInstallRequest(BaseModel):
    tenant_id: str
    provider_id: str
    config: dict[str, Any] | None = None


class IntegrationRequestCreate(BaseModel):
    tenant_id: str
    requested_name: str
    category: str
    use_case: str
    contact: str | None = None
    github_username: str | None = None


class IntegrationRequestApproveBody(BaseModel):
    approver_id: str | None = None
    approver_name: str | None = None


class IntegrationRequestRejectBody(BaseModel):
    reason: str | None = None


class IntegrationTestRequest(BaseModel):
    tenant_id: str
    provider_id: str
    config: dict[str, Any] | None = None


class IntegrationConfigRequest(BaseModel):
    tenant_id: str
    provider_id: str
    config: dict[str, Any] | None = None


class VaultRotateRequest(BaseModel):
    new_key_id: str | None = None
    new_key_material: str | None = None
    batch_size: int = 100


class VaultRotateResumeRequest(BaseModel):
    job_id: str


def _integration_connectivity_result(provider: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = config or {}
    required = ["api_key OR (username + password)"]
    has_api_key = bool(str(cfg.get("api_key", "")).strip())
    has_user_creds = bool(str(cfg.get("username", "")).strip() and str(cfg.get("password", "")).strip())
    passed = has_api_key or has_user_creds
    missing: list[str] = [] if passed else ["api_key", "username", "password"]
    status = "pass" if passed else "fail"
    checks = [
        {
            "check": "auth_material_present",
            "passed": passed,
            "accepted": ["api_key", "username+password"],
            "missing_fields": missing,
        }
    ]
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "provider_id": provider["id"],
        "status": status,
        "checks": checks,
        "latency_ms": latency_ms,
        "required_config_fields": required,
        "missing_fields": missing,
    }


def _normalize_provider_status(connection_status: str, connectivity_status: str, missing_fields: list[str]) -> str:
    conn = (connection_status or "").strip().lower()
    check = (connectivity_status or "").strip().lower()
    if conn == "disabled":
        return "unknown"
    if conn == "error":
        return "down"
    if check == "pass":
        return "healthy" if not missing_fields else "degraded"
    if check == "fail":
        return "degraded"
    return "unknown"


def _config_completeness(required_count: int, missing_count: int) -> float:
    if required_count <= 0:
        return 100.0
    present = max(0, required_count - max(0, missing_count))
    return round((present / required_count) * 100, 1)


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo_status():
    # Lightweight runtime SLO surface for local/prod dashboards.
    m = get_metrics()
    cur = m.request_count_summary()
    return {
        "service": "integration-ingress",
        "availability_target": 99.9,
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 500,
        "error_budget_window_days": 30,
        "targets_note": "See docs/docs/guides/service-slos-v1.md; HTTP counts from in-process middleware.",
        "current": {
            **cur,
            "kms_provider": _vault.provider,
            "rotation_jobs": int(_kms_metrics.get("rotation_jobs", 0)),
            "rotation_failures": int(_kms_metrics.get("rotation_failures", 0)),
        },
    }


@app.get("/v1/vault/kms")
async def vault_kms_status(_user=Depends(require_role("admin"))):
    issues = _validate_kms_config()
    return {
        "provider": _vault.provider,
        "active_key_id": _vault.active_key_id,
        "rotation_enabled": settings.kms_rotation_enabled,
        "rotation_interval_seconds": settings.kms_rotation_interval_seconds,
        "config_valid": len(issues) == 0,
        "config_issues": issues,
    }


@app.get("/v1/vault/kms/self-check")
async def vault_kms_self_check(_user=Depends(require_role("admin"))):
    issues = _validate_kms_config()
    if issues:
        return {"ok": False, "issues": issues}
    probe_key = _vault.active_key_id
    probe = b"tarka-kms-self-check"
    t0 = time.perf_counter()
    try:
        cipher = _kms.encrypt(probe, key_id=probe_key)
        plain = _kms.decrypt(cipher, key_id=probe_key)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {"ok": plain == probe, "latency_ms": elapsed, "provider": _vault.provider, "key_id": probe_key}
    except Exception:
        logger.exception("KMS self-check encrypt/decrypt round-trip failed")
        return {
            "ok": False,
            "error": "kms_round_trip_failed",
            "provider": _vault.provider,
            "key_id": probe_key,
        }


@app.get("/v1/vault/metrics")
async def vault_metrics(_user=Depends(require_role("admin"))):
    merged = dict(_kms_metrics)
    merged.update(_vault.metrics())
    return {"provider": _vault.provider, "metrics": merged}


@app.get("/v1/vault/rotation-jobs")
async def vault_rotation_jobs(session: AsyncSession = Depends(get_session), _user=Depends(require_role("admin"))):
    rows = (await session.execute(select(KMSRotationJob).order_by(KMSRotationJob.created_at.desc()).limit(20))).scalars().all()
    return {
        "jobs": [
            {
                "id": str(r.id),
                "provider": r.provider,
                "old_key_id": r.old_key_id,
                "new_key_id": r.new_key_id,
                "status": r.status,
                "total_secrets": r.total_secrets,
                "processed": r.processed,
                "rotated": r.rotated,
                "failed": r.failed,
                "checkpoint_offset": r.checkpoint_offset,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@app.post("/v1/vault/rotate")
async def rotate_vault_key(
    body: VaultRotateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("admin")),
):
    issues = _validate_kms_config()
    if issues:
        raise HTTPException(status_code=400, detail="; ".join(issues))
    new_key_id = (body.new_key_id or f"v{int(time.time())}").strip()
    new_key_material = (body.new_key_material or f"{settings.integration_vault_key}:{new_key_id}").strip()
    batch_size = max(10, min(1000, int(body.batch_size or 100)))
    job = KMSRotationJob(
        provider=_vault.provider,
        old_key_id=_vault.active_key_id,
        new_key_id=new_key_id,
        status="running",
        batch_size=batch_size,
    )
    session.add(job)
    await session.flush()
    processed_total = 0
    rotated_total = 0
    failed_total = 0
    offset = 0
    while True:
        try:
            processed, rotated, total = await _vault.rotate_secrets_batch(
                session,
                new_key_id=new_key_id,
                new_key_material=new_key_material,
                batch_size=batch_size,
                offset=offset,
            )
            if processed == 0:
                job.status = "completed"
                break
            processed_total += processed
            rotated_total += rotated
            offset += processed
            job.total_secrets = total
            job.processed = processed_total
            job.rotated = rotated_total
            job.checkpoint_offset = offset
            await session.flush()
        except Exception as exc:
            failed_total += 1
            job.failed = failed_total
            job.status = "failed"
            job.error_message = str(exc)
            session.add(
                KMSRotationFailure(
                    job_id=job.id,
                    secret_id=None,
                    key_id=new_key_id,
                    error_message=str(exc),
                )
            )
            _kms_metrics["rotation_failures"] = int(_kms_metrics["rotation_failures"]) + 1
            break
    _kms_metrics["rotation_jobs"] = int(_kms_metrics["rotation_jobs"]) + 1
    actor = get_current_user(request).user_id
    await _trail.record(
        session,
        actor=actor,
        action="vault_rotate",
        resource_type="kms_rotation_job",
        resource_id=str(job.id),
        changes={"old_key_id": job.old_key_id, "new_key_id": new_key_id, "status": job.status},
        tenant_id="system",
    )
    await session.commit()
    return {
        "ok": job.status == "completed",
        "job_id": str(job.id),
        "rotated": rotated_total,
        "processed": processed_total,
        "failed": failed_total,
        "active_key_id": _vault.active_key_id,
        "status": job.status,
    }


@app.post("/v1/vault/rotate/resume")
async def resume_vault_rotate(
    body: VaultRotateResumeRequest,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("admin")),
):
    job_q = await session.execute(select(KMSRotationJob).where(KMSRotationJob.id == body.job_id))
    job = job_q.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="rotation job not found")
    if job.status == "completed":
        return {"ok": True, "status": "completed", "job_id": str(job.id)}
    job.status = "running"
    offset = int(job.checkpoint_offset or 0)
    while True:
        try:
            processed, rotated, total = await _vault.rotate_secrets_batch(
                session,
                new_key_id=job.new_key_id,
                new_key_material=f"{settings.integration_vault_key}:{job.new_key_id}",
                batch_size=max(10, int(job.batch_size or 100)),
                offset=offset,
            )
            if processed == 0:
                job.status = "completed"
                break
            offset += processed
            job.total_secrets = total
            job.processed += processed
            job.rotated += rotated
            job.checkpoint_offset = offset
            await session.flush()
        except Exception as exc:
            job.failed += 1
            job.status = "failed"
            job.error_message = str(exc)
            session.add(
                KMSRotationFailure(
                    job_id=job.id,
                    secret_id=None,
                    key_id=job.new_key_id,
                    error_message=str(exc),
                )
            )
            break
    await session.commit()
    return {"ok": job.status == "completed", "status": job.status, "job_id": str(job.id), "processed": job.processed}


@app.get("/v1/adapters")
async def list_adapters():
    return {"adapters": list(ADAPTERS.keys())}


@app.post("/v1/webhooks/kyc/{provider}")
async def kyc_webhook(
    provider: str,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    event_id = uuid.uuid4()
    # Persist raw webhook
    record = WebhookInbox(
        id=event_id,
        provider=provider,
        raw_payload=payload,
        status="received",
    )
    session.add(record)

    # Attempt normalization via adapter
    normalized = None
    adapter_fn = ADAPTERS.get(provider)
    if adapter_fn:
        try:
            normalized = await adapter_fn("", "", payload)
            record.normalized = normalized
            record.status = "normalized"
        except Exception:
            record.status = "normalization_failed"

    await session.commit()
    return {"event_id": str(event_id), "provider": provider, "accepted": True, "normalized": normalized is not None}


@app.post("/v1/kyc/verify")
async def kyc_verify(body: KycVerifyRequest):
    merged = dict(body.raw or {})
    if body.document:
        merged["document"] = body.document
    return await verify(body.adapter, body.tenant_id, body.subject_id, merged)


@app.post("/v1/enrich")
async def enrich_entity(body: EnrichRequest, request: Request):
    """Quick digital footprint enrichment (legacy lightweight endpoint)."""
    http: httpx.AsyncClient = request.app.state.http
    results: dict[str, Any] = {}
    if body.email:
        results["email"] = await enrich_email(body.email, http)
    if body.phone:
        results["phone"] = await enrich_phone(body.phone)
    if body.ip:
        results["ip"] = await enrich_ip(body.ip, http)

    total_risk = sum(r.get("risk_score", 0) for r in results.values()) / max(len(results), 1)
    return {"enrichments": results, "aggregate_risk_score": round(total_risk, 1)}


@app.post("/v1/osint")
async def osint_enrichment(body: OsintRequest, request: Request):
    """Comprehensive OSINT enrichment across multiple intelligence sources.

    Queries up to 10 OSINT providers in parallel:
    - IP: Shodan InternetDB, AbuseIPDB, GreyNoise, IPinfo, ip-api
    - Email: EmailRep.io, Gravatar, HIBP, DNS MX, local heuristics
    - Phone: NumVerify, local heuristics
    - Domain: RDAP/WHOIS
    - Identity: GitHub profile discovery

    Returns a composite risk score (0-100) with risk level classification.
    """
    http: httpx.AsyncClient = request.app.state.http
    return await full_osint_enrichment(
        email=body.email,
        phone=body.phone,
        ip=body.ip,
        domain=body.domain,
        http=http,
        cfg=_osint_cfg,
    )


@app.get("/v1/osint/sources")
async def osint_sources():
    """List available OSINT sources and their configuration status."""
    return {
        "sources": {
            "ip": [
                {"name": "Shodan InternetDB", "requires_key": False, "configured": True},
                {"name": "AbuseIPDB", "requires_key": True, "configured": bool(_osint_cfg.abuseipdb_key)},
                {"name": "GreyNoise Community", "requires_key": False, "configured": True, "note": "API key optional for higher limits"},
                {"name": "IPinfo Lite", "requires_key": False, "configured": True, "note": "Token optional for higher limits"},
                {"name": "ip-api.com", "requires_key": False, "configured": True},
            ],
            "email": [
                {"name": "EmailRep.io", "requires_key": False, "configured": True, "note": "API key optional for higher limits"},
                {"name": "Gravatar", "requires_key": False, "configured": True},
                {"name": "Have I Been Pwned", "requires_key": False, "configured": True, "note": "Paid key needed for full breach data"},
                {"name": "DNS MX", "requires_key": False, "configured": True},
                {"name": "Local Heuristics", "requires_key": False, "configured": True},
            ],
            "phone": [
                {"name": "NumVerify", "requires_key": True, "configured": bool(_osint_cfg.numverify_key)},
                {"name": "Local Heuristics", "requires_key": False, "configured": True},
            ],
            "domain": [
                {"name": "RDAP (WHOIS successor)", "requires_key": False, "configured": True},
            ],
            "identity": [
                {"name": "GitHub Profile", "requires_key": False, "configured": True},
            ],
        },
        "total_sources": 12,
        "configured_without_keys": 9,
    }


@app.get("/v1/integrations/catalog")
async def integrations_catalog():
    return {
        "total_providers": len(PROVIDER_CATALOG),
        "connector_quality_version": CONNECTOR_QUALITY_VERSION,
        "categories": list_categories(),
        "providers": PROVIDER_CATALOG,
    }


class PreflightProbesRequest(BaseModel):
    """Run public doc + sandbox semantic probes without tenant credentials."""

    provider_ids: list[str] | None = None


@app.post("/v1/integrations/preflight-probes")
async def preflight_integration_probes(body: PreflightProbesRequest, request: Request):
    """Contract probe runner for connector catalog entries (no secrets; GET vendor doc URLs)."""
    http: httpx.AsyncClient = request.app.state.http
    want = body.provider_ids
    targets: list[dict[str, Any]] = []
    if want:
        for pid in want:
            p = get_provider(str(pid).strip())
            if p:
                targets.append(p)
    else:
        targets = list(PROVIDER_CATALOG)
    results: list[dict[str, Any]] = []
    for provider in targets:
        probe_ok, probe_latency, probe_error = await _live_provider_probe(provider, http)
        cq = _connector_quality_v1_from_probe(
            provider,
            probe_ok=probe_ok,
            probe_latency_ms=probe_latency,
            probe_error=probe_error,
        )
        results.append(
            {
                "provider_id": provider["id"],
                "name": provider.get("name"),
                "category": provider.get("category"),
                "swimlane_module": provider.get("swimlane_module"),
                "github_project_view_url": provider.get("github_project_view_url"),
                "live_probe": {"ok": probe_ok, "latency_ms": probe_latency, "error": probe_error},
                "connector_quality": cq,
            }
        )
    ok_n = sum(1 for r in results if r["live_probe"]["ok"])
    avg_score = round(sum(r["connector_quality"]["score"] for r in results) / max(len(results), 1), 1) if results else 0.0
    return {
        "connector_quality_version": CONNECTOR_QUALITY_VERSION,
        "probed": len(results),
        "probes_ok": ok_n,
        "average_connector_quality": avg_score,
        "results": results,
    }


async def _get_operation_snapshot(
    session: AsyncSession, *, tenant_id: str, provider_id: str, action: str, idempotency_key: str | None
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    result = await session.execute(
        select(IntegrationOperation).where(
            IntegrationOperation.tenant_id == tenant_id,
            IntegrationOperation.provider_id == provider_id,
            IntegrationOperation.action == action,
            IntegrationOperation.idempotency_key == idempotency_key,
        )
    )
    row = result.scalar_one_or_none()
    return dict(row.response_snapshot) if row else None


async def _save_operation_snapshot(
    session: AsyncSession, *, tenant_id: str, provider_id: str, action: str, idempotency_key: str | None, snapshot: dict[str, Any]
) -> None:
    if not idempotency_key:
        return
    session.add(
        IntegrationOperation(
            tenant_id=tenant_id,
            provider_id=provider_id,
            action=action,
            idempotency_key=idempotency_key,
            response_snapshot=snapshot,
        )
    )


def _enforce_policy_for_install(provider: dict[str, Any], region: str | None) -> None:
    profile = get_profile(region or "global")
    category = str(provider.get("category", ""))
    blocked = {"social_media", "crm"} if profile.restrict_cross_border else set()
    if category in blocked:
        raise HTTPException(
            status_code=400,
            detail=f"category '{category}' blocked for region '{profile.region.value}' due to cross-border restrictions",
        )


def _parsed_url_hostname(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _host_matches_expected(hostname: str, expected: str) -> bool:
    """True if hostname equals expected or is a subdomain of it (e.g. api.stripe.com vs stripe.com)."""
    host = hostname.lower().rstrip(".")
    exp = expected.lower().strip().rstrip(".")
    if not host or not exp:
        return False
    return host == exp or host.endswith("." + exp)


async def _live_provider_probe(provider: dict[str, Any], http: httpx.AsyncClient) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    url = str(provider.get("doc_url", "")).strip()
    if not url:
        return False, 0.0, "missing_doc_url"
    try:
        resp = await http.get(url, timeout=4.0)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if 200 <= resp.status_code < 400:
            pid = str(provider.get("id", ""))
            expected = _PROVIDER_SANDBOX_PROBES.get(pid)
            if expected:
                text = (getattr(resp, "text", None) or "").lower()
                host_hint = expected.get("host_hint", "")
                path_hint = expected.get("path_hint", "")
                host = _parsed_url_hostname(url)
                if host in ("testserver", "localhost", "127.0.0.1"):
                    return True, latency_ms, ""
                if host_hint and not _host_matches_expected(host, host_hint):
                    return False, latency_ms, "host_hint_mismatch"
                url_path = (urlparse(url).path or "/").lower()
                if path_hint and path_hint not in text and path_hint not in url_path:
                    return False, latency_ms, "sandbox_semantic_check_failed"
            return True, latency_ms, ""
        return False, latency_ms, f"http_{resp.status_code}"
    except Exception:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.exception("live provider probe request failed")
        return False, latency_ms, "live_probe_error"


@app.get("/v1/integrations/installed")
async def integrations_installed(tenant_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id))
    rows = result.scalars().all()
    items = []
    for row in rows:
        item = {
            "tenant_id": row.tenant_id,
            "provider_id": row.provider_id,
            "category": row.category,
            "status": row.status,
            "configured": row.configured,
            "version": row.version,
            "last_connectivity_test": row.last_connectivity_test,
            "masked_config": await _vault.get_masked_config(session, row.tenant_id, row.provider_id),
        }
        provider = get_provider(row.provider_id) or {}
        item["name"] = provider.get("name", row.provider_id)
        items.append(item)
    return {
        "tenant_id": tenant_id,
        "installed": items,
        "count": len(items),
    }


@app.get("/v1/integrations/readiness")
async def integrations_readiness(tenant_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(IntegrationConnection.category).where(IntegrationConnection.tenant_id == tenant_id))
    installed_categories = {str(r[0]) for r in result.all()}
    all_categories = set(list_categories())
    coverage = {}
    for c in sorted(all_categories):
        coverage[c] = {
            "installed": c in installed_categories,
            "count": 1 if c in installed_categories else 0,
        }
    score = round((len(installed_categories) / max(len(all_categories), 1)) * 100, 1)
    return {
        "tenant_id": tenant_id,
        "readiness_score": score,
        "covered_categories": len(installed_categories),
        "total_categories": len(all_categories),
        "coverage": coverage,
    }


@app.post("/v1/integrations/test-connectivity")
async def test_integration_connectivity(
    body: IntegrationTestRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    provider = get_provider(body.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"provider '{body.provider_id}' not found")
    effective_config = body.config if body.config is not None else await _vault.get_config(session, body.tenant_id, body.provider_id)
    result = _integration_connectivity_result(provider, effective_config)
    probe_ok, probe_latency, probe_error = await _live_provider_probe(provider, request.app.state.http)
    result["live_probe"] = {"ok": probe_ok, "latency_ms": probe_latency, "error": probe_error}
    hard_probe_failures = {"host_hint_mismatch", "sandbox_semantic_check_failed", "live_probe_error"}
    if not probe_ok and (probe_error in hard_probe_failures or str(probe_error).startswith("http_4") or str(probe_error).startswith("http_5")):
        result["status"] = "fail"
    q = await session.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == body.tenant_id,
            IntegrationConnection.provider_id == body.provider_id,
        )
    )
    row = q.scalar_one_or_none()
    if row:
        row.last_connectivity_test = result
        row.status = "enabled" if result["status"] == "pass" else "error"
    actor = get_current_user(request).user_id
    await _trail.record(
        session,
        actor=actor,
        action="test_connectivity",
        resource_type="integration",
        resource_id=body.provider_id,
        changes={"status": result["status"], "missing": result.get("missing_fields", [])},
        tenant_id=body.tenant_id,
    )
    await session.commit()
    return result


@app.get("/v1/integrations/health-matrix")
async def integration_health_matrix(tenant_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id))
    connections = result.scalars().all()
    rows: list[dict[str, Any]] = []
    for item in connections:
        provider_id = item.provider_id
        provider = get_provider(provider_id)
        if not provider:
            continue
        last = item.last_connectivity_test
        if not isinstance(last, dict):
            cfg = await _vault.get_config(session, tenant_id, provider_id)
            last = _integration_connectivity_result(provider, cfg)
        rows.append(
            {
                "provider_id": provider_id,
                "name": provider.get("name"),
                "category": provider.get("category"),
                "status": last.get("status"),
                "latency_ms": last.get("latency_ms"),
                "missing_fields": last.get("missing_fields", []),
            }
        )
    pass_count = sum(1 for r in rows if r.get("status") == "pass")
    score = round((pass_count / max(len(rows), 1)) * 100, 1) if rows else 0.0
    return {"tenant_id": tenant_id, "score": score, "rows": rows}


@app.get("/v1/integrations/scorecards")
async def integration_scorecards(tenant_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id))
    connections = result.scalars().all()
    providers: list[dict[str, Any]] = []
    for item in connections:
        provider = get_provider(item.provider_id) or {}
        last = item.last_connectivity_test if isinstance(item.last_connectivity_test, dict) else {}
        check_status = str(last.get("status", "unknown"))
        latency_ms = float(last.get("latency_ms", 0.0) or 0.0)
        missing_fields = last.get("missing_fields", [])
        if not isinstance(missing_fields, list):
            missing_fields = []
        reasons: list[str] = []
        live_probe = last.get("live_probe")
        if isinstance(live_probe, dict) and live_probe.get("error"):
            reasons.append(str(live_probe.get("error")))
        reasons.extend(str(x) for x in missing_fields)
        if str(item.status).lower() == "error":
            reasons.append("connection_error_status")
        required_fields = provider.get("required_config_fields", [])
        required_count = len(required_fields) if isinstance(required_fields, list) else 0
        status = _normalize_provider_status(str(item.status), check_status, missing_fields)
        connectivity_score = 100.0 if check_status == "pass" else (35.0 if check_status == "fail" else 50.0)
        config_completeness = _config_completeness(required_count, len(missing_fields))
        provider_score = round((connectivity_score * 0.7) + (config_completeness * 0.3), 1)
        cq = _connector_quality_v1_installed(provider, last if isinstance(last, dict) else {})
        providers.append(
            {
                "provider_id": item.provider_id,
                "category": item.category,
                "status": status,
                "connectivity_score": connectivity_score,
                "latency_ms": round(latency_ms, 2),
                "config_completeness": config_completeness,
                "last_checked_at": item.updated_at.isoformat() if item.updated_at else None,
                "reasons": sorted(set(reasons)),
                "provider_score": provider_score,
                "connector_quality": cq,
            }
        )
    overall_score = round(sum(p["provider_score"] for p in providers) / max(len(providers), 1), 1) if providers else 0.0
    overall_cq = round(sum(p["connector_quality"]["score"] for p in providers) / max(len(providers), 1), 1) if providers else 0.0
    return {
        "tenant_id": tenant_id,
        "connector_quality_version": CONNECTOR_QUALITY_VERSION,
        "overall_score": overall_score,
        "overall_connector_quality": overall_cq,
        "providers": providers,
    }


@app.post("/v1/integrations/install")
async def install_integration(
    body: IntegrationInstallRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _user=Depends(require_role("admin")),
):
    provider = get_provider(body.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"provider '{body.provider_id}' not found")
    snap = await _get_operation_snapshot(session, tenant_id=body.tenant_id, provider_id=body.provider_id, action="install", idempotency_key=idempotency_key)
    if snap:
        return snap
    _enforce_policy_for_install(provider, (body.config or {}).get("region"))
    config = body.config or {}
    if config:
        await _vault.set_config(session, body.tenant_id, str(provider["id"]), config)
    q = await session.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == body.tenant_id,
            IntegrationConnection.provider_id == str(provider["id"]),
        )
    )
    row = q.scalar_one_or_none()
    if row:
        row.status = "enabled"
        row.configured = bool(config) or row.configured
        row.version += 1
    else:
        row = IntegrationConnection(
            tenant_id=body.tenant_id,
            provider_id=str(provider["id"]),
            category=str(provider["category"]),
            status="enabled",
            configured=bool(config),
            version=1,
        )
        session.add(row)
    item = {
        "tenant_id": body.tenant_id,
        "provider_id": provider["id"],
        "name": provider["name"],
        "category": provider["category"],
        "status": "enabled",
        "configured": bool(config) or bool(row.configured),
        "masked_config": await _vault.get_masked_config(session, body.tenant_id, str(provider["id"])),
    }
    actor = get_current_user(request).user_id
    await _trail.record(
        session,
        actor=actor,
        action="install_integration",
        resource_type="integration",
        resource_id=str(provider["id"]),
        changes={"status": {"old": None if row.version == 1 else "updated", "new": "enabled"}},
        tenant_id=body.tenant_id,
    )
    snapshot = {"ok": True, "integration": item}
    await _save_operation_snapshot(
        session,
        tenant_id=body.tenant_id,
        provider_id=body.provider_id,
        action="install",
        idempotency_key=idempotency_key,
        snapshot=snapshot,
    )
    await session.commit()
    return snapshot


@app.post("/v1/integrations/uninstall")
async def uninstall_integration(
    body: IntegrationInstallRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("admin")),
):
    q = await session.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == body.tenant_id,
            IntegrationConnection.provider_id == body.provider_id,
        )
    )
    row = q.scalar_one_or_none()
    removed = False
    if row:
        row.status = "disabled"
        row.version += 1
        removed = True
        actor = get_current_user(request).user_id
        await _trail.record(
            session,
            actor=actor,
            action="uninstall_integration",
            resource_type="integration",
            resource_id=body.provider_id,
            changes={"status": {"old": "enabled", "new": "disabled"}},
            tenant_id=body.tenant_id,
        )
    await session.commit()
    return {"ok": removed, "removed_provider_id": body.provider_id}


@app.get("/v1/integrations/config/{provider_id}")
async def get_integration_config(provider_id: str, tenant_id: str, session: AsyncSession = Depends(get_session), _user=Depends(require_role("analyst"))):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"provider '{provider_id}' not found")
    return {
        "tenant_id": tenant_id,
        "provider_id": provider_id,
        "required_config_fields": provider.get("required_config_fields", []),
        "masked_config": await _vault.get_masked_config(session, tenant_id, provider_id),
    }


@app.post("/v1/integrations/configure")
async def configure_integration(
    body: IntegrationConfigRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _user=Depends(require_role("admin")),
):
    provider = get_provider(body.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"provider '{body.provider_id}' not found")
    snap = await _get_operation_snapshot(session, tenant_id=body.tenant_id, provider_id=body.provider_id, action="configure", idempotency_key=idempotency_key)
    if snap:
        return snap
    await _vault.set_config(session, body.tenant_id, body.provider_id, body.config or {})
    q = await session.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == body.tenant_id,
            IntegrationConnection.provider_id == body.provider_id,
        )
    )
    row = q.scalar_one_or_none()
    if row:
        row.configured = True
        row.version += 1
    actor = get_current_user(request).user_id
    await _trail.record(
        session,
        actor=actor,
        action="configure_integration",
        resource_type="integration",
        resource_id=body.provider_id,
        changes={"configured": {"old": False, "new": True}},
        tenant_id=body.tenant_id,
    )
    snapshot = {
        "ok": True,
        "tenant_id": body.tenant_id,
        "provider_id": body.provider_id,
        "masked_config": await _vault.get_masked_config(session, body.tenant_id, body.provider_id),
    }
    await _save_operation_snapshot(
        session,
        tenant_id=body.tenant_id,
        provider_id=body.provider_id,
        action="configure",
        idempotency_key=idempotency_key,
        snapshot=snapshot,
    )
    await session.commit()
    return snapshot


def _build_github_issue_url(req: dict[str, Any]) -> str:
    title = quote_plus(f"Integration request: {req['requested_name']}")
    issue_body = quote_plus(
        f"Tenant: {req['tenant_id']}\n"
        f"Category: {req['category']}\n"
        f"Use case: {req['use_case']}\n"
        f"Contact: {req.get('contact') or ''}\n"
        f"GitHub user: {req.get('github_username') or ''}\n"
        f"Request ID: {req['id']}\n"
        f"Approved by: {req.get('approved_by_name') or req.get('approved_by') or 'admin'}"
    )
    return f"https://github.com/pamu512/tarka/issues/new?title={title}&body={issue_body}"


@app.post("/v1/integrations/request")
async def request_integration(body: IntegrationRequestCreate):
    """Queue a new integration request. GitHub issue URL is issued only after admin approval."""
    req = {
        "id": str(uuid.uuid4()),
        "tenant_id": body.tenant_id,
        "requested_name": body.requested_name.strip(),
        "category": body.category.strip(),
        "use_case": body.use_case.strip(),
        "contact": (body.contact or "").strip(),
        "github_username": (body.github_username or "").strip(),
        "status": "pending_approval",
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "github_issue_url": None,
        "approved_at": None,
        "approved_by": None,
        "approved_by_name": None,
    }
    _integration_requests.append(req)
    return {
        "ok": True,
        "request": req,
        "status": "pending_approval",
        "github_issue_url": None,
        "message": (
            "Request submitted for admin review. A prefilled GitHub issue for engineering will be available after an administrator approves this request."
        ),
    }


@app.get("/v1/integrations/requests")
async def list_integration_requests(
    tenant_id: str | None = None,
    status: str | None = None,
    _admin=Depends(require_role("admin")),
):
    """List integration requests (admin). Pending items await approval before a dev ticket URL exists."""
    out = list(reversed(_integration_requests))
    if tenant_id:
        out = [r for r in out if r["tenant_id"] == tenant_id]
    if status:
        out = [r for r in out if r.get("status") == status]
    return {"items": out, "count": len(out)}


@app.post("/v1/integrations/requests/{request_id}/approve")
async def approve_integration_request(
    request_id: str,
    body: IntegrationRequestApproveBody,
    request: Request,
    _admin=Depends(require_role("admin")),
):
    """Approve a pending request and generate the GitHub new-issue URL for developers."""
    req = next((r for r in _integration_requests if r["id"] == request_id), None)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.get("status") == "approved" and req.get("github_issue_url"):
        return {
            "ok": True,
            "request": req,
            "github_issue_url": req["github_issue_url"],
            "already_approved": True,
        }
    if req.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail="request is not pending approval")
    actor = get_current_user(request)
    req["status"] = "approved"
    req["approved_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req["approved_by"] = (body.approver_id or "").strip() or str(actor.user_id)
    req["approved_by_name"] = (body.approver_name or "").strip() or str(actor.user_id)
    url = _build_github_issue_url(req)
    req["github_issue_url"] = url
    return {"ok": True, "request": req, "github_issue_url": url}


@app.post("/v1/integrations/requests/{request_id}/reject")
async def reject_integration_request(
    request_id: str,
    body: IntegrationRequestRejectBody,
    request: Request,
    _admin=Depends(require_role("admin")),
):
    req = next((r for r in _integration_requests if r["id"] == request_id), None)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail="request is not pending approval")
    actor = get_current_user(request)
    req["status"] = "rejected"
    req["rejected_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req["rejected_by"] = str(actor.user_id)
    req["rejection_reason"] = (body.reason or "").strip()
    return {"ok": True, "request": req}
