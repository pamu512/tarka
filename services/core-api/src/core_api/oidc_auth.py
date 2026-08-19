"""OIDC authorization-code BFF for the investigator desk.

Local desk (``OIDC_ISSUER`` empty): ``GET /auth/config`` returns
``{oidc_enabled: false}`` and login does not redirect to an IdP.
When the issuer is set, ``OIDC_CLIENT_ID`` is required — missing client
id fails closed with HTTP 503 instead of silently verifying JWTs only.

Login state and one-time tickets live in Redis (``REDIS_URL``) so SSO
works with ``coreApi.replicaCount`` > 1 without sticky sessions. Tokens
are set on httpOnly cookies and are never returned in JSON or placed on
a redirect URL.

``POST /auth/refresh`` reads the ``tarka_refresh`` cookie only — a JSON
``refresh_token`` body is rejected. When ``TARKA_DEPLOYMENT_PROFILE`` is
``production`` and ``OIDC_ISSUER`` is set, Redis is mandatory: empty
``REDIS_URL`` or connect/SET/GET failure refuses start and/or returns
503. In-process ``_login_states`` / ``_tickets`` stay for local/tests
when OIDC is off or the profile is not production. Production does not
require ``OIDC_ISSUER`` (API keys remain the machine path).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

log = logging.getLogger("oidc-auth")

router = APIRouter(tags=["auth"])

STATE_TTL_S = 600
TICKET_TTL_S = 90
DISCOVERY_TTL_S = 3600
DEFAULT_SCOPES = "openid profile email offline_access"

ACCESS_COOKIE = "tarka_access"
REFRESH_COOKIE = "tarka_refresh"
STATE_KEY_PREFIX = "oidc:state:"
TICKET_KEY_PREFIX = "oidc:ticket:"

# In-process fallback when REDIS_URL is unset (local / unit tests).
_login_states: dict[str, dict[str, Any]] = {}
_tickets: dict[str, dict[str, Any]] = {}
_discovery: dict[str, Any] = {}
_discovery_at: float = 0.0
_redis_client: Any = None
_redis_url_bound: str | None = None


def reset_oidc_state_for_tests() -> None:
    """Clear in-memory OIDC state and Redis client (tests only)."""
    global _discovery, _discovery_at, _redis_client, _redis_url_bound
    _login_states.clear()
    _tickets.clear()
    _discovery = {}
    _discovery_at = 0.0
    _redis_client = None
    _redis_url_bound = None


def _now() -> float:
    return time.time()


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def oidc_issuer() -> str:
    return _env("OIDC_ISSUER").rstrip("/")


def oidc_client_id() -> str:
    return _env("OIDC_CLIENT_ID")


def oidc_client_secret() -> str:
    return _env("OIDC_CLIENT_SECRET")


def oidc_scopes() -> str:
    return _env("OIDC_SCOPES") or DEFAULT_SCOPES


def redis_url() -> str:
    return _env("REDIS_URL")


def deployment_profile_is_production() -> bool:
    return _env("TARKA_DEPLOYMENT_PROFILE").lower() == "production"


def oidc_requires_redis() -> bool:
    """Shared Redis is mandatory when production SSO is enabled.

    Replica count > 1 cannot share in-process ``_login_states``.
    Production without an issuer (API-key machine path) does not
    require Redis for OIDC.
    """
    return deployment_profile_is_production() and bool(oidc_issuer())


def _redis_required_detail() -> str:
    return (
        "REDIS_URL is required when TARKA_DEPLOYMENT_PROFILE=production "
        "and OIDC_ISSUER is set (no in-process OIDC state fallback)"
    )


def enforce_oidc_redis_for_production() -> None:
    """Refuse process start when production SSO cannot share login state."""
    if not oidc_requires_redis():
        return
    if not redis_url():
        raise RuntimeError(_redis_required_detail())


def _raise_if_redis_required() -> None:
    if oidc_requires_redis() and not redis_url() and _redis_client is None:
        raise HTTPException(status_code=503, detail=_redis_required_detail())


def _misconfigured_detail() -> str:
    return "OIDC_ISSUER is set but OIDC_CLIENT_ID is empty; desk SSO cannot start (fail closed)"


def _raise_if_issuer_without_client_id() -> None:
    if oidc_issuer() and not oidc_client_id():
        raise HTTPException(status_code=503, detail=_misconfigured_detail())


def _require_oidc_ready() -> None:
    _raise_if_issuer_without_client_id()
    if not oidc_issuer():
        raise HTTPException(status_code=404, detail="OIDC is not enabled (local mode)")
    _raise_if_redis_required()


def _purge_expired() -> None:
    now = _now()
    for store, ttl in ((_login_states, STATE_TTL_S), (_tickets, TICKET_TTL_S)):
        for key in [k for k, v in store.items() if now - float(v.get("created_at", 0)) > ttl]:
            store.pop(key, None)


def _bind_redis(client: Any) -> None:
    """Test hook: inject a Redis-like client (fakeredis / mock)."""
    global _redis_client, _redis_url_bound
    _redis_client = client
    _redis_url_bound = redis_url() or "mock://test"


async def _redis() -> Any | None:
    """Return a Redis client when REDIS_URL is set; otherwise None (memory).

    Production + issuer never falls back to the in-process maps.
    """
    global _redis_client, _redis_url_bound
    url = redis_url()
    if not url:
        if _redis_client is not None:
            return _redis_client
        _raise_if_redis_required()
        return None
    if _redis_client is not None and _redis_url_bound == url:
        return _redis_client
    try:
        import redis.asyncio as redis_async
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="Redis client unavailable for OIDC state"
        ) from exc
    try:
        _redis_client = redis_async.from_url(url, decode_responses=True)
        _redis_url_bound = url
    except Exception as exc:
        log.warning("OIDC Redis connect failed: %s", exc)
        raise HTTPException(status_code=503, detail="OIDC state store unavailable") from exc
    return _redis_client


async def _store_put(kind: str, key: str, value: dict[str, Any], ttl: int) -> None:
    client = await _redis()
    payload = dict(value)
    payload.setdefault("created_at", _now())
    if client is not None:
        prefix = STATE_KEY_PREFIX if kind == "state" else TICKET_KEY_PREFIX
        try:
            await client.set(f"{prefix}{key}", json.dumps(payload), ex=ttl)
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("OIDC Redis SET failed: %s", exc)
            raise HTTPException(status_code=503, detail="OIDC state store unavailable") from exc
        return
    _raise_if_redis_required()
    store = _login_states if kind == "state" else _tickets
    store[key] = payload


async def _store_pop(kind: str, key: str) -> dict[str, Any] | None:
    client = await _redis()
    if client is not None:
        prefix = STATE_KEY_PREFIX if kind == "state" else TICKET_KEY_PREFIX
        rkey = f"{prefix}{key}"
        try:
            getter = getattr(client, "getdel", None)
            if getter is not None:
                raw = await getter(rkey)
            else:
                raw = await client.get(rkey)
                if raw is not None:
                    await client.delete(rkey)
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("OIDC Redis GETDEL failed: %s", exc)
            raise HTTPException(status_code=503, detail="OIDC state store unavailable") from exc
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    _raise_if_redis_required()
    store = _login_states if kind == "state" else _tickets
    return store.pop(key, None)


def desk_origin(request: Request) -> str:
    explicit = _env("OIDC_REDIRECT_ORIGIN") or _env("DESK_ORIGIN")
    if explicit:
        return explicit.rstrip("/")
    proto = (
        (request.headers.get("x-forwarded-proto") or request.url.scheme or "http")
        .split(",")[0]
        .strip()
    )
    host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    )
    host = str(host).split(",")[0].strip()
    return f"{proto}://{host}"


def idp_redirect_uri(request: Request) -> str:
    return f"{desk_origin(request)}/api/auth/callback"


def safe_next(raw: str | None) -> str:
    if not raw:
        return "/cases"
    value = raw.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/cases"
    return value


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _cookie_secure(request: Request) -> bool:
    proto = (
        (request.headers.get("x-forwarded-proto") or request.url.scheme or "http")
        .split(",")[0]
        .strip()
        .lower()
    )
    if proto == "https":
        return True
    return _env("TARKA_DEPLOYMENT_PROFILE").lower() == "production"


def _apply_session_cookies(
    response: JSONResponse,
    request: Request,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_in: Any,
) -> None:
    try:
        max_age = int(expires_in) if expires_in is not None else 3600
    except (TypeError, ValueError):
        max_age = 3600
    if max_age < 1:
        max_age = 3600
    secure = _cookie_secure(request)
    common = {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(ACCESS_COOKIE, access_token, max_age=max_age, **common)
    if refresh_token:
        response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=30 * 24 * 3600, **common)


async def fetch_discovery() -> dict[str, Any]:
    global _discovery, _discovery_at
    issuer = oidc_issuer()
    if (
        _discovery
        and _discovery.get("_issuer") == issuer
        and _now() - _discovery_at < DISCOVERY_TTL_S
    ):
        return _discovery
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        log.warning("OIDC discovery failed for %s: %s", issuer, exc)
        raise HTTPException(status_code=502, detail="OIDC discovery failed") from exc
    if (
        not isinstance(data, dict)
        or not data.get("authorization_endpoint")
        or not data.get("token_endpoint")
    ):
        raise HTTPException(
            status_code=502, detail="OIDC discovery missing authorization or token endpoint"
        )
    data["_issuer"] = issuer
    _discovery = data
    _discovery_at = _now()
    return data


async def _token_request(token_endpoint: str, data: dict[str, str]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("OIDC token endpoint failed: %s", exc)
        raise HTTPException(status_code=502, detail="OIDC token exchange failed") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise HTTPException(status_code=502, detail="OIDC token endpoint returned no access_token")
    return payload


@router.get("/config")
async def auth_config() -> dict[str, Any]:
    _raise_if_issuer_without_client_id()
    issuer = oidc_issuer()
    return {"oidc_enabled": bool(issuer)}


@router.get("/login")
async def login(
    request: Request, next_path: str = Query("/cases", alias="next")
) -> RedirectResponse:
    _require_oidc_ready()
    _purge_expired()
    disco = await fetch_discovery()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    redirect_uri = idp_redirect_uri(request)
    await _store_put(
        "state",
        state,
        {
            "created_at": _now(),
            "code_verifier": verifier,
            "next": safe_next(next_path),
            "redirect_uri": redirect_uri,
        },
        STATE_TTL_S,
    )
    params = {
        "response_type": "code",
        "client_id": oidc_client_id(),
        "redirect_uri": redirect_uri,
        "scope": oidc_scopes(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize = str(disco["authorization_endpoint"])
    sep = "&" if "?" in authorize else "?"
    return RedirectResponse(url=f"{authorize}{sep}{urlencode(params)}", status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    _require_oidc_ready()
    _purge_expired()
    if error:
        raise HTTPException(
            status_code=400,
            detail=error_description or error,
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing OIDC code or state")
    stored = await _store_pop("state", state)
    if not stored:
        raise HTTPException(status_code=400, detail="invalid or expired OIDC state")
    disco = await fetch_discovery()
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": str(stored["redirect_uri"]),
        "client_id": oidc_client_id(),
        "code_verifier": str(stored["code_verifier"]),
    }
    secret = oidc_client_secret()
    if secret:
        form["client_secret"] = secret
    tokens = await _token_request(str(disco["token_endpoint"]), form)
    ticket = secrets.token_urlsafe(32)
    await _store_put(
        "ticket",
        ticket,
        {
            "created_at": _now(),
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or None,
            "expires_in": tokens.get("expires_in"),
            "token_type": tokens.get("token_type") or "Bearer",
            "next": stored.get("next") or "/cases",
        },
        TICKET_TTL_S,
    )
    dest = f"{desk_origin(request)}/auth/callback?ticket={ticket}"
    return RedirectResponse(url=dest, status_code=302)


class SessionBody(BaseModel):
    ticket: str = Field(min_length=1)


def _session_json(next_path: str) -> dict[str, Any]:
    return {"authenticated": True, "next": next_path}


@router.post("/session")
async def session(request: Request, body: SessionBody) -> JSONResponse:
    _require_oidc_ready()
    _purge_expired()
    stored = await _store_pop("ticket", body.ticket.strip())
    if not stored:
        raise HTTPException(status_code=400, detail="invalid or already-used ticket")
    next_path = str(stored.get("next") or "/cases")
    response = JSONResponse(_session_json(next_path))
    _apply_session_cookies(
        response,
        request,
        access_token=str(stored["access_token"]),
        refresh_token=stored.get("refresh_token") or None,
        expires_in=stored.get("expires_in"),
    )
    return response


async def _reject_refresh_token_json_body(request: Request) -> None:
    """Cookie is the only refresh secret — refuse a JSON body token."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type != "application/json":
        return
    try:
        payload = await request.json()
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    raw = payload.get("refresh_token")
    if isinstance(raw, str) and raw.strip():
        raise HTTPException(
            status_code=400,
            detail="refresh_token in JSON body is not accepted; use the tarka_refresh cookie",
        )


@router.post("/refresh")
async def refresh(request: Request) -> JSONResponse:
    _require_oidc_ready()
    await _reject_refresh_token_json_body(request)
    presented = (request.cookies.get(REFRESH_COOKIE) or "").strip()
    if not presented:
        raise HTTPException(status_code=400, detail="missing refresh token")
    disco = await fetch_discovery()
    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": presented,
        "client_id": oidc_client_id(),
    }
    secret = oidc_client_secret()
    if secret:
        form["client_secret"] = secret
    tokens = await _token_request(str(disco["token_endpoint"]), form)
    next_refresh = tokens.get("refresh_token") or presented
    response = JSONResponse({"authenticated": True})
    _apply_session_cookies(
        response,
        request,
        access_token=str(tokens["access_token"]),
        refresh_token=next_refresh,
        expires_in=tokens.get("expires_in"),
    )
    return response
