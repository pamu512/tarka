import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.adapters import ADAPTERS, register_adapter, verify
from integration_ingress.config import settings
from integration_ingress.db import get_session, init_db
from integration_ingress.enrichment import enrich_email, enrich_ip, enrich_phone
from integration_ingress.models import WebhookInbox
from integration_ingress.osint import OsintConfig, full_osint_enrichment

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from observability import setup_observability  # noqa: E402

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


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    await init_db()
    yield
    await application.state.http.aclose()


app = FastAPI(
    title="Tarka Integration Ingress",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "integration-ingress")


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


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


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
