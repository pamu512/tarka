"""Shared X-API-Key authentication dependency for all services."""
from __future__ import annotations

import os

from fastapi import HTTPException, Request


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
        return
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
