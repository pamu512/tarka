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
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("auth-rbac")

ROLE_HIERARCHY = {"admin": 4, "analyst": 3, "viewer": 2, "service": 1}

# OIDC config
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.environ.get("OIDC_AUDIENCE", "tarka")
OIDC_JWKS_URL = os.environ.get("OIDC_JWKS_URL", "")
OIDC_ROLES_CLAIM = os.environ.get("OIDC_ROLES_CLAIM", "roles")

_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0


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
        raise HTTPException(401, f"JWT verification failed: {e}")


class AuthUser:
    """Represents an authenticated user or service."""
    def __init__(self, user_id: str, roles: list[str], auth_type: str, claims: dict[str, Any] | None = None):
        self.user_id = user_id
        self.roles = roles
        self.auth_type = auth_type
        self.claims = claims or {}

    @property
    def best_role(self) -> str:
        if not self.roles:
            return "viewer"
        return max(self.roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))

    def has_role(self, required: str) -> bool:
        required_level = ROLE_HIERARCHY.get(required, 0)
        return any(ROLE_HIERARCHY.get(r, 0) >= required_level for r in self.roles)


async def _authenticate(request: Request) -> AuthUser:
    """Extract and validate credentials from request."""
    api_key = request.headers.get("x-api-key", "")
    api_keys_raw = os.environ.get("API_KEYS", "").strip()
    valid_keys = frozenset(k.strip() for k in api_keys_raw.split(",") if k.strip()) if api_keys_raw else frozenset()

    if api_key:
        if valid_keys and api_key in valid_keys:
            return AuthUser(user_id="service", roles=["service", "admin"], auth_type="api_key")
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
        return AuthUser(user_id=user_id, roles=roles, auth_type="jwt", claims=claims)

    if not valid_keys and not OIDC_ISSUER:
        return AuthUser(user_id="anonymous", roles=["admin"], auth_type="none")

    raise HTTPException(401, "authentication required")


class AuthMiddleware(BaseHTTPMiddleware):
    """Injects AuthUser into request.state.auth_user."""
    SKIP_PATHS = {"/v1/health", "/metrics", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.SKIP_PATHS:
            request.state.auth_user = AuthUser("system", ["admin"], "bypass")
            return await call_next(request)
        try:
            request.state.auth_user = await _authenticate(request)
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
    return getattr(request.state, "auth_user", AuthUser("anonymous", ["viewer"], "none"))


def setup_auth(app: FastAPI) -> None:
    """Install auth middleware on the app."""
    app.add_middleware(AuthMiddleware)
