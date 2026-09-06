"""Shared audit-first primitives for Tarka v2."""

from __future__ import annotations

from typing import Any

__all__ = ["AuditLog"]


def __getattr__(name: str) -> Any:
    if name == "AuditLog":
        from .audit_trail import AuditLog

        return AuditLog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
