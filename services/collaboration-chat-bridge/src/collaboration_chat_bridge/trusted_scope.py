"""Trusted tenant/analyst scope headers (isolated from bridge secret validation for CodeQL)."""

from __future__ import annotations

from fastapi import Request


def trusted_scope_headers(request: Request) -> tuple[str, str]:
    tenant = (
        request.headers.get("X-Tenant-Id") or request.headers.get("X-Tarka-Tenant-Id") or ""
    ).strip()
    analyst = (
        request.headers.get("X-Analyst-Id") or request.headers.get("X-Tarka-Analyst-Id") or ""
    ).strip()
    return tenant, analyst
