"""OIDC BFF: local mode, Redis state/tickets, httpOnly cookie sessions."""

from __future__ import annotations

import json
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


class FakeRedis:
    """Minimal async Redis stand-in for OIDC state/tickets."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.ttls.pop(key, None)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(oidc_auth.router, prefix="/auth")
    return app


def _client() -> TestClient:
    return TestClient(_app(), base_url="https://desk.example.test")


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    oidc_auth.reset_oidc_state_for_tests()
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
    monkeypatch.delenv("OIDC_REDIRECT_ORIGIN", raising=False)
    monkeypatch.delenv("DESK_ORIGIN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
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


def _set_cookie_headers(response) -> str:
    getter = getattr(response.headers, "get_list", None)
    if getter is not None:
        return " ".join(getter("set-cookie"))
    raw = response.headers.get("set-cookie") or ""
    return raw


def test_config_oidc_disabled_when_issuer_unset():
    with _client() as client:
        resp = client.get("/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"oidc_enabled": False}


def test_login_does_not_redirect_to_idp_when_issuer_unset():
    with _client() as client:
        resp = client.get("/auth/login?next=/cases", follow_redirects=False)
    assert resp.status_code == 404
    location = resp.headers.get("location") or ""
    assert "idp.example.test" not in location
    assert resp.status_code != 302


def test_login_and_callback_503_when_issuer_set_without_client_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    with _client() as client:
        login = client.get("/auth/login?next=/cases", follow_redirects=False)
        callback = client.get("/auth/callback?code=x&state=y", follow_redirects=False)
        config = client.get("/auth/config")
    assert login.status_code == 503
    assert "OIDC_CLIENT_ID" in login.json()["detail"]
    assert callback.status_code == 503
    assert "OIDC_CLIENT_ID" in callback.json()["detail"]
    assert config.status_code == 503


def _oidc_ready(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, str]]]:
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "desk-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "desk-secret")
    return _install_idp(monkeypatch)


def test_happy_path_cookie_session_no_token_in_json(monkeypatch: pytest.MonkeyPatch):
    seen = _oidc_ready(monkeypatch)

    with _client() as client:
        login = client.get(
            "/auth/login?next=/rules/visual", headers=DESK_HEADERS, follow_redirects=False
        )
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

        session = client.post("/auth/session", json={"ticket": ticket}, headers=DESK_HEADERS)
        assert session.status_code == 200
        body = session.json()
        assert "access_token" not in body
        assert "refresh_token" not in body
        assert body["authenticated"] is True
        assert body["next"] == "/rules/visual"
        assert session.cookies.get(oidc_auth.ACCESS_COOKIE) == "access-from-idp"
        assert session.cookies.get(oidc_auth.REFRESH_COOKIE) == "refresh-from-idp"
        set_cookie = _set_cookie_headers(session).lower()
        assert "httponly" in set_cookie
        assert "secure" in set_cookie
        assert "samesite=lax" in set_cookie

        replay = client.post("/auth/session", json={"ticket": ticket}, headers=DESK_HEADERS)
        assert replay.status_code == 400

        refreshed = client.post("/auth/refresh", json={}, headers=DESK_HEADERS)
        assert refreshed.status_code == 200
        assert "access_token" not in refreshed.json()
        assert "refresh_token" not in refreshed.json()
        assert refreshed.cookies.get(oidc_auth.ACCESS_COOKIE) == "access-refreshed"
        assert refreshed.cookies.get(oidc_auth.REFRESH_COOKIE) == "refresh-rotated"

    assert seen["token"][0]["grant_type"] == "authorization_code"
    assert seen["token"][0]["code"] == "valid-code"
    assert seen["token"][0]["code_verifier"]
    assert seen["token"][0]["client_secret"] == "desk-secret"
    assert seen["token"][1]["grant_type"] == "refresh_token"


def test_redis_backed_state_and_tickets_shared_across_stores(monkeypatch: pytest.MonkeyPatch):
    _oidc_ready(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://oidc-test:6379/0")
    fake = FakeRedis()
    oidc_auth._bind_redis(fake)

    with _client() as client:
        login = client.get("/auth/login?next=/cases", headers=DESK_HEADERS, follow_redirects=False)
        assert login.status_code == 302
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        assert any(k.startswith(oidc_auth.STATE_KEY_PREFIX) for k in fake.data)
        raw_state = fake.data[f"{oidc_auth.STATE_KEY_PREFIX}{state}"]
        assert json.loads(raw_state)["code_verifier"]
        assert fake.ttls[f"{oidc_auth.STATE_KEY_PREFIX}{state}"] == oidc_auth.STATE_TTL_S

        callback = client.get(
            f"/auth/callback?code=valid-code&state={state}",
            headers=DESK_HEADERS,
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert f"{oidc_auth.STATE_KEY_PREFIX}{state}" not in fake.data
        ticket = parse_qs(urlparse(callback.headers["location"]).query)["ticket"][0]
        assert f"{oidc_auth.TICKET_KEY_PREFIX}{ticket}" in fake.data
        assert fake.ttls[f"{oidc_auth.TICKET_KEY_PREFIX}{ticket}"] == oidc_auth.TICKET_TTL_S

        session = client.post("/auth/session", json={"ticket": ticket}, headers=DESK_HEADERS)
        assert session.status_code == 200
        assert "access_token" not in session.json()
        assert f"{oidc_auth.TICKET_KEY_PREFIX}{ticket}" not in fake.data
        assert session.cookies.get(oidc_auth.ACCESS_COOKIE) == "access-from-idp"
