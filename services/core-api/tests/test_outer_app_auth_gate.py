"""Gate: outer core-api app runs auth middleware (omni-search is no longer unauthenticated).

Demo contract: ``ALLOW_INSECURE_NO_AUTH=true`` keeps every outer-app route open
(anonymous viewer), matching the lite compose day-1 walk. With auth configured
(``API_KEYS``), the same routes fail closed without a valid key.

Auth env is read per request, so one app instance serves all cases; the otel
guard is reset around its creation (same pattern as test_lifespan_observability).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi.testclient import TestClient  # noqa: E402

from core_api.main import create_app  # noqa: E402


def _reset_otel_guard() -> None:
    from core_api.infrastructure import otel as _otel

    _otel._INITIALIZED = False
    _otel._INIT_ATTEMPTED = False


@pytest.fixture(scope="module")
def outer_app():
    _reset_otel_guard()
    yield create_app()
    _reset_otel_guard()


def _clean_auth_env(monkeypatch) -> None:
    for key in ("API_KEYS", "OIDC_ISSUER", "OIDC_JWKS_URL", "TENANT_BINDING_REQUIRED"):
        monkeypatch.delenv(key, raising=False)


def test_omni_search_open_in_insecure_demo_mode(outer_app, monkeypatch) -> None:
    _clean_auth_env(monkeypatch)
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    client = TestClient(outer_app)  # no lifespan: auth middleware runs per-request regardless
    r = client.get("/v1/omni-search", params={"q": ""})
    assert r.status_code == 200, r.text
    assert r.json() == {"entities": [], "cases": [], "rules": []}


def test_omni_search_503_when_auth_misconfigured(outer_app, monkeypatch) -> None:
    _clean_auth_env(monkeypatch)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)

    client = TestClient(outer_app)
    r = client.get("/v1/omni-search", params={"q": ""})
    assert r.status_code == 503
    assert "ALLOW_INSECURE_NO_AUTH" in r.text or "API_KEYS" in r.text


def test_omni_search_requires_api_key_when_configured(outer_app, monkeypatch) -> None:
    _clean_auth_env(monkeypatch)
    monkeypatch.setenv("API_KEYS", "test-key-1")

    client = TestClient(outer_app)

    denied = client.get("/v1/omni-search", params={"q": ""})
    assert denied.status_code == 401

    allowed = client.get(
        "/v1/omni-search", params={"q": ""}, headers={"X-API-Key": "test-key-1"}
    )
    assert allowed.status_code == 200, allowed.text

    wrong = client.get(
        "/v1/omni-search", params={"q": ""}, headers={"X-API-Key": "not-the-key"}
    )
    assert wrong.status_code == 401


def test_health_stays_open_even_with_auth(outer_app, monkeypatch) -> None:
    _clean_auth_env(monkeypatch)
    monkeypatch.setenv("API_KEYS", "test-key-1")

    client = TestClient(outer_app)
    r = client.get("/v1/health")
    assert r.status_code == 200
