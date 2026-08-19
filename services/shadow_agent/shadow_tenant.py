"""Tenant binding for Shadow analyze — reuses services/shared tenant_binding."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

_shared = Path(__file__).resolve().parents[1] / "shared"
if _shared.is_dir() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from tenant_binding import (  # noqa: E402
    TenantMapConfigError,
    parse_api_key_tenant_map,
    request_tenant_id,
    tenant_binding_required,
    tenants_from_claims,
)

# Same messages as services/shared/tenant_binding.enforce_tenant_access / auth.require_api_key.
_TENANT_REQUIRED = "tenant_id is required"
_NO_SCOPE = "tenant binding is required but caller has no tenant scope"
_MAP_REQUIRED = "API_KEY_TENANT_MAP is required when TENANT_BINDING_REQUIRED is set"


class UnscopedTenantReadError(RuntimeError):
    """Binding is required but the read was not given a tenant — fail closed."""

    def __init__(
        self,
        message: str = "tenant_id is required to scope shadow reads",
        *,
        status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _is_tenant_allowed(allowed_tenants: set[str], tenant_id: str) -> bool:
    return "*" in allowed_tenants or tenant_id in allowed_tenants


def _claims_from_request(request: Request) -> dict[str, Any] | None:
    user = getattr(request.state, "auth_user", None)
    claims = getattr(user, "claims", None) if user is not None else None
    return claims if isinstance(claims, dict) else None


def require_tenant_for_read(tenant_id: str | None) -> str | None:
    """Return a stripped tenant or None when binding is off.

    When ``TENANT_BINDING_REQUIRED`` is on, a missing tenant fails closed (503)
    so callers never run an unscoped history/graph read.
    """
    tid = (tenant_id or "").strip() or None
    if tenant_binding_required() and tid is None:
        raise UnscopedTenantReadError(
            "tenant_id is required to scope shadow reads when TENANT_BINDING_REQUIRED is set",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return tid


async def bind_analyze_tenant(
    request: Request,
    *,
    credential: str | None,
) -> str | None:
    """Resolve the analyze tenant using the shared ingest binding language.

    Binding off (local / OIDC-off / compose desk): return ``None`` so callers
    keep single-tenant ``DEFAULT_TENANT_ID`` behavior.

    Binding on: require a real tenant (header / body / JWT claims) and a map or
    claims. Missing or unparseable ``API_KEY_TENANT_MAP`` → 503. Empty tenant →
    400. Tenant outside caller scope → 403.
    """
    if not tenant_binding_required():
        return None

    try:
        tenant_map = parse_api_key_tenant_map()
    except TenantMapConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    claims = _claims_from_request(request)
    claim_tenants = tenants_from_claims(claims)
    user = getattr(request.state, "auth_user", None)
    user_tenants = getattr(user, "tenant_ids", None) if user is not None else None
    if isinstance(user_tenants, set) and user_tenants:
        allowed: set[str] | None = user_tenants
    elif claim_tenants:
        allowed = claim_tenants
    elif tenant_map:
        key = (request.headers.get("x-api-key") or credential or "").strip()
        allowed = tenant_map.get(key, set())
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_MAP_REQUIRED,
        )

    tid = await request_tenant_id(request)
    if not tid and len(claim_tenants) == 1:
        tid = next(iter(claim_tenants))
    if not tid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_TENANT_REQUIRED)
    if allowed is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NO_SCOPE)
    if not _is_tenant_allowed(allowed, tid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"tenant '{tid}' is outside caller scope",
        )
    return tid
