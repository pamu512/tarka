"""Tenant event_type overlay. Query lands in the HTTP overlay task."""

from __future__ import annotations


async def load_names_or_empty(session, tenant_id: str) -> frozenset[str]:
    return frozenset()
