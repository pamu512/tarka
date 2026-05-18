from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from tenant_binding import enforce_tenant_access, parse_api_key_tenant_map, tenant_binding_required, tenants_from_claims

"""Tarka shared SSO (OIDC/JWT) + RBAC middleware.

Supports two authentication modes:
  1. API Key (X-API-Key header) — for service-to-service calls
  2. JWT Bearer token — for human users via OIDC SSO

Role hierarchy: admin > analyst > viewer > service

Usage::

    from auth_rbac import setup_auth, require_role
    setup_auth(app, service_name="decision-api")

    @app.get("/admin-only", dependencies=[Depends(require_role("admin"))])
    async def admin_endpoint(): ...
"""
log = logging.getLogger("auth-rbac")

ROLE_HIERARCHY = {"admin": 4, "analyst": 3, "viewer": 2, "service": 1}

# OIDC config
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.environ.get("OIDC_AUDIENCE", "tarka")
OIDC_JWKS_URL = os.environ.get("OIDC_JWKS_URL", "")
OIDC_ROLES_CLAIM = os.environ.get("OIDC_ROLES_CLAIM", "roles")

_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0


def _allow_insecure_no_auth() -> bool:
    return os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}


async def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache and time.time() - _jwks_fetched_at < 3600:
        return _jwks_cache
    jwks_url = OIDC_JWKS_URL
    if not jwks_url and OIDC_ISSUER:
        async with httpx.AsyncClient() as client:
            disco = await client.get(f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration", timeout=10)
            disco.raise_for_status()
            jwks_url = disco.json().get("jwks_uri", "")
    if not jwks_url:
        return {}
    async with httpx.AsyncClient() as client:
        r = await client.get(jwks_url, timeout=10)
        r.raise_for_status()
        _jwks_cache = r.json()
        _jwks_fetched_at = time.time()
        return _jwks_cache


async def _verify_jwt(token: str) -> dict[str, Any]:
    """Verify JWT signature and return claims. NEVER falls back to unverified decode."""
    try:
        import jwt as pyjwt
    except ImportError:
        raise HTTPException(401, "PyJWT not installed — cannot verify JWT tokens")

    jwks = await _fetch_jwks()
    if not jwks or not jwks.get("keys"):
        raise HTTPException(401, "JWKS unavailable — cannot verify JWT signature")

    try:
        from jwt import PyJWKClient

        jwk_client = PyJWKClient("")
        jwk_client.jwk_set = pyjwt.PyJWKSet.from_dict(jwks)
        header = pyjwt.get_unverified_header(token)
        key = jwk_client.get_signing_key(header.get("kid", ""))
        return pyjwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER or None,
        )
    except Exception as e:
        log.warning("JWT verification failed: %s", e)
        raise HTTPException(401, "JWT verification failed")


class AuthUser:
    """Represents an authenticated user or service."""

    def __init__(
        self,
        user_id: str,
        roles: list[str],
        auth_type: str,
        claims: dict[str, Any] | None = None,
        tenant_ids: set[str] | None = None,
    ):
        self.user_id = user_id
        self.roles = roles
        self.auth_type = auth_type
        self.claims = claims or {}
        self.tenant_ids = tenant_ids if tenant_ids is not None else set()

    @property
    def best_role(self) -> str:
        if not self.roles:
            return "viewer"
        return max(self.roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))

    def has_role(self, required: str) -> bool:
        required_level = ROLE_HIERARCHY.get(required, 0)
        return any(ROLE_HIERARCHY.get(r, 0) >= required_level for r in self.roles)

    def allows_tenant(self, tenant_id: str) -> bool:
        if not self.tenant_ids:
            return False
        return "*" in self.tenant_ids or tenant_id in self.tenant_ids


async def _authenticate(request: Request) -> AuthUser:
    """Extract and validate credentials from request."""
    api_key = request.headers.get("x-api-key", "")
    api_keys_raw = os.environ.get("API_KEYS", "").strip()
    valid_keys = frozenset(k.strip() for k in api_keys_raw.split(",") if k.strip()) if api_keys_raw else frozenset()
    key_tenant_map = parse_api_key_tenant_map()

    allow_insecure = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}

    if api_key:
        if valid_keys and api_key in valid_keys:
            role = os.environ.get("SERVICE_API_KEY_ROLE", "admin").strip().lower()
            if role not in ROLE_HIERARCHY:
                role = "admin"
            roles = sorted({"service", role})
            tenant_ids = key_tenant_map.get(api_key, set()) if key_tenant_map else {"*"}
            return AuthUser(user_id="service", roles=roles, auth_type="api_key", tenant_ids=tenant_ids)
        if valid_keys:
            raise HTTPException(401, "invalid API key")

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
        claims = await _verify_jwt(token)
        user_id = claims.get("sub", claims.get("email", "unknown"))
        roles = claims.get(OIDC_ROLES_CLAIM, ["viewer"])
        if isinstance(roles, str):
            roles = [roles]
        tenant_ids = tenants_from_claims(claims)
        return AuthUser(user_id=user_id, roles=roles, auth_type="jwt", claims=claims, tenant_ids=tenant_ids)

    if not valid_keys and not OIDC_ISSUER:
        if allow_insecure:
            return AuthUser(user_id="anonymous", roles=["viewer"], auth_type="none", tenant_ids={"*"})
        raise HTTPException(
            503,
            "authentication misconfigured: set API_KEYS or OIDC_ISSUER (or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )

    raise HTTPException(401, "authentication required")


class AuthMiddleware(BaseHTTPMiddleware):
    """Injects AuthUser into request.state.auth_user."""

    # Shell UI (AnalystReadinessBar) calls these without X-API-Key via nginx /api/decisions/* proxy.
    # They return non-secret operational metadata (OSS #36 / #51); same trust model as /v1/health.
    SKIP_PATHS = frozenset(
        {
            "/v1/health",
            "/metrics",
            "/v1/slo",
            "/v1/ops/evaluation-posture",
        }
    )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.SKIP_PATHS:
            request.state.auth_user = AuthUser("system", ["viewer"], "bypass", tenant_ids={"*"})
            return await call_next(request)
        try:
            user = await _authenticate(request)
            request.state.auth_user = user
            if tenant_binding_required():
                await enforce_tenant_access(request, allowed_tenants=user.tenant_ids)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(401, str(e))
        return await call_next(request)


def require_role(role: str):
    """FastAPI dependency that checks the user has the given role."""

    async def _check(request: Request) -> AuthUser:
        user: AuthUser = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(401, "not authenticated")
        if not user.has_role(role):
            raise HTTPException(403, f"role '{role}' required, you have {user.roles}")
        return user

    return _check


def get_current_user(request: Request) -> AuthUser:
    return getattr(request.state, "auth_user", AuthUser("anonymous", ["viewer"], "none", tenant_ids=set()))


def setup_auth(app: FastAPI) -> None:
    """Install auth middleware on the app."""
    app.add_middleware(AuthMiddleware)
