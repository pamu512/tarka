"""OIDC authorization-code BFF for the investigator desk.

Local desk (``OIDC_ISSUER`` empty): ``GET /auth/config`` returns
``{oidc_enabled: false}`` and login does not redirect to an IdP.
When the issuer is set, ``OIDC_CLIENT_ID`` is required — missing client
id fails closed with HTTP 503 instead of silently verifying JWTs only.

Tokens stay on the server until the SPA redeems a one-time ticket; they
are never placed on a redirect URL.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

log = logging.getLogger("oidc-auth")

router = APIRouter(tags=["auth"])

STATE_TTL_S = 600
TICKET_TTL_S = 90
DISCOVERY_TTL_S = 3600
DEFAULT_SCOPES = "openid profile email offline_access"

# Single-process stores. Multi-replica deploys should move these to Redis.
_login_states: dict[str, dict[str, Any]] = {}
_tickets: dict[str, dict[str, Any]] = {}
_discovery: dict[str, Any] = {}
_discovery_at: float = 0.0


def reset_oidc_state_for_tests() -> None:
    """Clear in-memory OIDC state (tests only)."""
    global _discovery, _discovery_at
    _login_states.clear()
    _tickets.clear()
    _discovery = {}
    _discovery_at = 0.0


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


def _misconfigured_detail() -> str:
    return "OIDC_ISSUER is set but OIDC_CLIENT_ID is empty; desk SSO cannot start (fail closed)"


def _raise_if_issuer_without_client_id() -> None:
    if oidc_issuer() and not oidc_client_id():
        raise HTTPException(status_code=503, detail=_misconfigured_detail())


def _require_oidc_ready() -> None:
    _raise_if_issuer_without_client_id()
    if not oidc_issuer():
        raise HTTPException(status_code=404, detail="OIDC is not enabled (local mode)")


def _purge_expired() -> None:
    now = _now()
    for store, ttl in ((_login_states, STATE_TTL_S), (_tickets, TICKET_TTL_S)):
        for key in [k for k, v in store.items() if now - float(v.get("created_at", 0)) > ttl]:
            store.pop(key, None)


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
    _login_states[state] = {
        "created_at": _now(),
        "code_verifier": verifier,
        "next": safe_next(next_path),
        "redirect_uri": redirect_uri,
    }
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
    stored = _login_states.pop(state, None)
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
    _tickets[ticket] = {
        "created_at": _now(),
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token") or None,
        "expires_in": tokens.get("expires_in"),
        "token_type": tokens.get("token_type") or "Bearer",
        "next": stored.get("next") or "/cases",
    }
    dest = f"{desk_origin(request)}/auth/callback?ticket={ticket}"
    return RedirectResponse(url=dest, status_code=302)


class SessionBody(BaseModel):
    ticket: str = Field(min_length=1)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=1)


@router.post("/session")
async def session(body: SessionBody) -> dict[str, Any]:
    _require_oidc_ready()
    _purge_expired()
    stored = _tickets.pop(body.ticket.strip(), None)
    if not stored:
        raise HTTPException(status_code=400, detail="invalid or already-used ticket")
    return {
        "access_token": stored["access_token"],
        "refresh_token": stored.get("refresh_token"),
        "token_type": stored.get("token_type") or "Bearer",
        "expires_in": stored.get("expires_in"),
        "next": stored.get("next") or "/cases",
    }


@router.post("/refresh")
async def refresh(body: RefreshBody) -> dict[str, Any]:
    _require_oidc_ready()
    disco = await fetch_discovery()
    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": body.refresh_token,
        "client_id": oidc_client_id(),
    }
    secret = oidc_client_secret()
    if secret:
        form["client_secret"] = secret
    tokens = await _token_request(str(disco["token_endpoint"]), form)
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token") or body.refresh_token,
        "token_type": tokens.get("token_type") or "Bearer",
        "expires_in": tokens.get("expires_in"),
    }
