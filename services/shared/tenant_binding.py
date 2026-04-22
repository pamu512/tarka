from __future__ import annotations

"""Shared tenant binding helpers for API-key and JWT-protected services."""


import json
import os
from typing import Any

from fastapi import HTTPException, Request


def tenant_binding_required() -> bool:
    return os.environ.get("TENANT_BINDING_REQUIRED", "").strip().lower() in {"1", "true", "yes", "on"}


def parse_api_key_tenant_map() -> dict[str, set[str]]:
    raw = os.environ.get("API_KEY_TENANT_MAP", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, set[str]] = {}
    for key, value in payload.items():
        k = str(key).strip()
        if not k:
            continue
        if isinstance(value, str):
            v = value.strip()
            out[k] = {v} if v else set()
            continue
        if isinstance(value, list):
            vals = {str(item).strip() for item in value if str(item).strip()}
            out[k] = vals
            continue
        out[k] = set()
    return out


def tenants_from_claims(claims: dict[str, Any] | None) -> set[str]:
    if not isinstance(claims, dict):
        return set()
    # Support common claim names/operators can map in IdP.
    candidates = [
        claims.get("tenant_id"),
        claims.get("tenant"),
        claims.get("tenant_ids"),
        claims.get("tenants"),
    ]
    out: set[str] = set()
    for item in candidates:
        if isinstance(item, str):
            val = item.strip()
            if val:
                out.add(val)
        elif isinstance(item, list):
            for v in item:
                sv = str(v).strip()
                if sv:
                    out.add(sv)
    return out


async def request_tenant_id(request: Request) -> str | None:
    qp_tid = (request.query_params.get("tenant_id") or "").strip()
    if qp_tid:
        return qp_tid
    path_tid = str(request.path_params.get("tenant_id") or "").strip()
    if path_tid:
        return path_tid

    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" not in ctype:
        return None
    try:
        payload = await request.json()
    except Exception:
        return None
    if isinstance(payload, dict):
        tid = str(payload.get("tenant_id") or "").strip()
        return tid or None
    return None


def _is_tenant_allowed(allowed_tenants: set[str], tenant_id: str) -> bool:
    return "*" in allowed_tenants or tenant_id in allowed_tenants


async def enforce_tenant_access(
    request: Request,
    *,
    allowed_tenants: set[str] | None,
    strict: bool | None = None,
) -> None:
    if strict is None:
        strict = tenant_binding_required()
    if not strict:
        return
    tenant_id = await request_tenant_id(request)
    if not tenant_id:
        return
    if allowed_tenants is None:
        raise HTTPException(status_code=403, detail="tenant binding is required but caller has no tenant scope")
    if not _is_tenant_allowed(allowed_tenants, tenant_id):
        raise HTTPException(status_code=403, detail=f"tenant '{tenant_id}' is outside caller scope")
