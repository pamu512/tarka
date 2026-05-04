from __future__ import annotations

import httpx


def build_http_client(
    *,
    timeout_seconds: float = 10.0,
    connect_seconds: float = 3.0,
    max_connections: int = 100,
    max_keepalive_connections: int = 20,
) -> httpx.AsyncClient:
    """Create a consistent AsyncClient for Tarka services."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds, connect=connect_seconds),
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        ),
    )

