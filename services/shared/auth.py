from __future__ import annotations

import os

from fastapi import HTTPException, Request
from tenant_binding import (
    TenantMapConfigError,
    enforce_tenant_access,
    parse_api_key_tenant_map,
    tenant_binding_required,
)

"""Shared X-API-Key authentication dependency for all services."""


def _deployment_profile_is_production() -> bool:
    """TARKA_DEPLOYMENT_PROFILE=production fail-closes soft-open auth.

    API keys remain the machine path — OIDC_ISSUER is not required.
    """
    return os.environ.get("TARKA_DEPLOYMENT_PROFILE", "").strip().lower() == "production"


def _allow_insecure_no_auth() -> bool:
    if _deployment_profile_is_production():
        return False
    return os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_valid_keys() -> frozenset[str]:
    raw = os.environ.get("API_KEYS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


async def require_api_key(request: Request) -> None:
    # Orchestrators and scripts (e.g. infra/scripts/ci/full_stack_smoke.py) probe these without X-API-Key.
    if request.url.path in {
        "/v1/health",
        "/v1/ready",
        "/v1/health/deep",
        "/health",
        "/health/deep",
        "/metrics",
    }:
        return
    keys = _get_valid_keys()
    try:
        tenant_map = parse_api_key_tenant_map()
    except TenantMapConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not keys:
        allow = _allow_insecure_no_auth()
        if allow:
            if tenant_binding_required() and not tenant_map:
                raise HTTPException(
                    status_code=503,
                    detail="API_KEY_TENANT_MAP is required when TENANT_BINDING_REQUIRED is set",
                )
            await enforce_tenant_access(request, allowed_tenants={"*"})
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if tenant_map:
        await enforce_tenant_access(request, allowed_tenants=tenant_map.get(header, set()))
    elif tenant_binding_required():
        raise HTTPException(
            status_code=503,
            detail="API_KEY_TENANT_MAP is required when TENANT_BINDING_REQUIRED is set",
        )
