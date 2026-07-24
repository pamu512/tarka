"""Phase 0: API keys require explicit tenant scopes outside demo mode."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from auth_rbac import AuthMiddleware, _authenticate  # noqa: E402


def _request(headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/x",
        "raw_path": b"/v1/x",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    return Request(scope)


def test_api_key_without_tenant_map_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.delenv("API_KEY_TENANT_MAP", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)

    with pytest.raises(Exception) as exc:
        asyncio.run(_authenticate(_request({"x-api-key": "k1"})))
    assert getattr(exc.value, "status_code", None) == 503


def test_api_key_with_explicit_tenant_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"k1":["tenant-a"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)

    user = asyncio.run(_authenticate(_request({"x-api-key": "k1"})))
    assert user.allows_tenant("tenant-a")
    assert not user.allows_tenant("tenant-b")


def test_api_key_wildcard_only_via_explicit_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"k1":["*"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)

    user = asyncio.run(_authenticate(_request({"x-api-key": "k1"})))
    assert user.allows_tenant("any-tenant")


def test_auth_middleware_exempts_only_documented_probe_paths() -> None:
    expected_probes = {
        "/v1/health",
        "/v1/ready",
        "/v1/health/deep",
        "/health",
        "/health/deep",
    }
    assert expected_probes <= AuthMiddleware.SKIP_PATHS
    assert "/v1/chat" not in AuthMiddleware.SKIP_PATHS
    assert "/v1/decisions/evaluate" not in AuthMiddleware.SKIP_PATHS
