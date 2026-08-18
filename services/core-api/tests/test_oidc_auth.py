"""OIDC BFF: local mode, fail-closed client id, mocked IdP happy path."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core_api import oidc_auth  # noqa: E402


ISSUER = "https://idp.example.test"
DESK_HEADERS = {"host": "desk.example.test", "x-forwarded-proto": "https"}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(oidc_auth.router, prefix="/auth")
    return app


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    oidc_auth.reset_oidc_state_for_tests()
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
    monkeypatch.delenv("OIDC_REDIRECT_ORIGIN", raising=False)
    monkeypatch.delenv("DESK_ORIGIN", raising=False)
    yield
    oidc_auth.reset_oidc_state_for_tests()


def _install_idp(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, str]]]:
    seen: dict[str, list[dict[str, str]]] = {"token": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if path.endswith("/token"):
            body = dict(httpx.QueryParams(request.content.decode()))
            seen["token"].append(body)
            if body.get("grant_type") == "authorization_code":
                if body.get("code") != "valid-code":
                    return httpx.Response(400, json={"error": "invalid_code"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-from-idp",
                        "refresh_token": "refresh-from-idp",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            if body.get("grant_type") == "refresh_token":
                if body.get("refresh_token") != "refresh-from-idp":
                    return httpx.Response(400, json={"error": "invalid_refresh"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-refreshed",
                        "refresh_token": "refresh-rotated",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            return httpx.Response(400, json={"error": "unsupported_grant"})
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    monkeypatch.setattr(oidc_auth.httpx, "AsyncClient", factory)
    return seen


def test_config_oidc_disabled_when_issuer_unset():
    with TestClient(_app()) as client:
        resp = client.get("/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"oidc_enabled": False}


def test_login_does_not_redirect_to_idp_when_issuer_unset():
    with TestClient(_app()) as client:
        resp = client.get("/auth/login?next=/cases", follow_redirects=False)
    assert resp.status_code == 404
    location = resp.headers.get("location") or ""
    assert "idp.example.test" not in location
    assert resp.status_code != 302


def test_login_and_callback_503_when_issuer_set_without_client_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    with TestClient(_app()) as client:
        login = client.get("/auth/login?next=/cases", follow_redirects=False)
        callback = client.get("/auth/callback?code=x&state=y", follow_redirects=False)
        config = client.get("/auth/config")
    assert login.status_code == 503
    assert "OIDC_CLIENT_ID" in login.json()["detail"]
    assert callback.status_code == 503
    assert "OIDC_CLIENT_ID" in callback.json()["detail"]
    assert config.status_code == 503


def test_happy_path_ticket_session_refresh_no_token_in_location(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "desk-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "desk-secret")
    seen = _install_idp(monkeypatch)

    with TestClient(_app()) as client:
        login = client.get("/auth/login?next=/rules/visual", headers=DESK_HEADERS, follow_redirects=False)
        assert login.status_code == 302
        loc = login.headers["location"]
        parsed = urlparse(loc)
        assert parsed.scheme == "https"
        assert parsed.netloc == "idp.example.test"
        assert parsed.path == "/authorize"
        q = parse_qs(parsed.query)
        assert q["response_type"] == ["code"]
        assert q["client_id"] == ["desk-client"]
        assert q["code_challenge_method"] == ["S256"]
        assert q["redirect_uri"] == ["https://desk.example.test/api/auth/callback"]
        assert "access_token" not in loc
        state = q["state"][0]

        callback = client.get(
            f"/auth/callback?code=valid-code&state={state}",
            headers=DESK_HEADERS,
            follow_redirects=False,
        )
        assert callback.status_code == 302
        spa = callback.headers["location"]
        assert spa.startswith("https://desk.example.test/auth/callback?ticket=")
        assert "access_token" not in spa
        assert "refresh_token" not in spa
        ticket = parse_qs(urlparse(spa).query)["ticket"][0]

        session = client.post("/auth/session", json={"ticket": ticket})
        assert session.status_code == 200
        body = session.json()
        assert body["access_token"] == "access-from-idp"
        assert body["refresh_token"] == "refresh-from-idp"
        assert body["next"] == "/rules/visual"

        replay = client.post("/auth/session", json={"ticket": ticket})
        assert replay.status_code == 400

        refreshed = client.post("/auth/refresh", json={"refresh_token": "refresh-from-idp"})
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] == "access-refreshed"
        assert refreshed.json()["refresh_token"] == "refresh-rotated"

    assert seen["token"][0]["grant_type"] == "authorization_code"
    assert seen["token"][0]["code"] == "valid-code"
    assert seen["token"][0]["code_verifier"]
    assert seen["token"][0]["client_secret"] == "desk-secret"
    assert seen["token"][1]["grant_type"] == "refresh_token"

