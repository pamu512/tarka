"""Shared X-API-Key authentication dependency for all services."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request
from tenant_binding import enforce_tenant_access, parse_api_key_tenant_map


def _allow_insecure_no_auth() -> bool:
    return os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}


def _get_valid_keys() -> frozenset[str]:
    raw = os.environ.get("API_KEYS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


async def require_api_key(request: Request) -> None:
    # Orchestrators and scripts (e.g. scripts/ci/full_stack_smoke.py) probe these without X-API-Key.
    if request.url.path in {"/v1/health", "/metrics"}:
        return
    keys = _get_valid_keys()
    tenant_map = parse_api_key_tenant_map()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
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
