"""Mock JWKS: desk JWT roles come from the OIDC claim; API keys stay the machine path."""

from __future__ import annotations

import time

import httpx
import pytest

pytest.importorskip("cryptography")
pytest.importorskip("jwt")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402

import auth_rbac  # noqa: E402
from auth_rbac import require_role, setup_auth  # noqa: E402

ISSUER = "https://idp.example.test"
JWKS_URL = f"{ISSUER}/jwks"
AUDIENCE = "tarka"


@pytest.fixture
def rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@pytest.fixture(autouse=True)
def _reset_jwks(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", "")
    monkeypatch.setattr(auth_rbac, "OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(auth_rbac, "OIDC_JWKS_URL", "")
    monkeypatch.setattr(auth_rbac, "OIDC_ROLES_CLAIM", "roles")
    auth_rbac._jwks_cache = {}
    auth_rbac._jwks_fetched_at = 0.0
    yield
    auth_rbac._jwks_cache = {}
    auth_rbac._jwks_fetched_at = 0.0


def _jwk(public_key, kid: str) -> dict:
    body = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    body["kid"] = kid
    body["use"] = "sig"
    body["alg"] = "RS256"
    return body


def _token(private_key, *, kid: str, roles: list[str], claim: str = "roles") -> str:
    import jwt as pyjwt

    return pyjwt.encode(
        {
            "sub": "desk-human",
            claim: roles,
            "aud": AUDIENCE,
            "iss": ISSUER,
            "exp": int(time.time()) + 600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _install_jwks(monkeypatch, jwks: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == JWKS_URL:
            return httpx.Response(200, json=jwks)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    monkeypatch.setattr(auth_rbac.httpx, "AsyncClient", factory)


def _desk_app() -> FastAPI:
    app = FastAPI()
    setup_auth(app)

    @app.get("/whoami")
    async def whoami(request: Request):
        user = request.state.auth_user
        return {"user_id": user.user_id, "roles": user.roles, "auth_type": user.auth_type}

    @app.get("/analyst-only", dependencies=[Depends(require_role("analyst"))])
    async def analyst_only():
        return {"ok": True}

    return app


def test_empty_issuer_api_key_is_machine_path(monkeypatch):
    monkeypatch.setenv("API_KEYS", "machine-key")
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", "")
    with TestClient(_desk_app()) as client:
        denied = client.get("/whoami")
        machine = client.get("/whoami", headers={"X-API-Key": "machine-key"})
    assert denied.status_code == 401
    assert machine.status_code == 200
    body = machine.json()
    assert body["auth_type"] == "api_key"
    assert "service" in body["roles"]


def test_mock_jwks_maps_roles_claim_to_desk_roles(monkeypatch, rsa_pair):
    private_key, public_key = rsa_pair
    kid = "g4-test-1"
    _install_jwks(monkeypatch, {"keys": [_jwk(public_key, kid)]})
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(auth_rbac, "OIDC_JWKS_URL", JWKS_URL)
    monkeypatch.setattr(auth_rbac, "OIDC_ROLES_CLAIM", "roles")

    architect = _token(private_key, kid=kid, roles=["RiskArchitect"])
    investigator = _token(private_key, kid=kid, roles=["FraudAnalyst"])

    with TestClient(_desk_app()) as client:
        a = client.get("/whoami", headers={"Authorization": f"Bearer {architect}"})
        i = client.get("/whoami", headers={"Authorization": f"Bearer {investigator}"})
    assert a.status_code == 200, a.text
    assert a.json()["auth_type"] == "jwt"
    assert a.json()["roles"] == ["RiskArchitect"]
    assert i.status_code == 200, i.text
    assert i.json()["roles"] == ["FraudAnalyst"]


def test_mock_jwks_custom_roles_claim(monkeypatch, rsa_pair):
    private_key, public_key = rsa_pair
    kid = "g4-test-2"
    _install_jwks(monkeypatch, {"keys": [_jwk(public_key, kid)]})
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(auth_rbac, "OIDC_JWKS_URL", JWKS_URL)
    monkeypatch.setattr(auth_rbac, "OIDC_ROLES_CLAIM", "tarka_roles")

    token = _token(
        private_key, kid=kid, roles=["RiskArchitect"], claim="tarka_roles"
    )
    with TestClient(_desk_app()) as client:
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["roles"] == ["RiskArchitect"]
