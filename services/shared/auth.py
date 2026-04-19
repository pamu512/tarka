"""Shared X-API-Key authentication dependency for all services."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request


def _allow_insecure_no_auth() -> bool:
    return os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}


def _get_valid_keys() -> frozenset[str]:
    raw = os.environ.get("API_KEYS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


_valid_keys: frozenset[str] | None = None


def _keys() -> frozenset[str]:
    global _valid_keys
    if _valid_keys is None:
        _valid_keys = _get_valid_keys()
    return _valid_keys


async def require_api_key(request: Request) -> None:
    keys = _keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
