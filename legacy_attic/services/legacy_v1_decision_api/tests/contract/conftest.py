"""Shared fixtures for Schemathesis contract tests (FastAPI under mocks)."""

from __future__ import annotations

import pytest

from tests.contract.bootstrap_app import CONTRACT_API_KEY, ensure_patched_app


@pytest.fixture(scope="module")
def decision_app():
    """Same patched app singleton used by ``schemathesis_schemas`` (single patch lifecycle)."""
    return ensure_patched_app()


@pytest.fixture
def httpx_client(decision_app):
    """Starlette transport used for explicit binary / Content-Type fuzz (outside Schemathesis)."""
    from starlette.testclient import TestClient

    with TestClient(
        decision_app,
        raise_server_exceptions=False,
        headers={"X-API-Key": CONTRACT_API_KEY},
    ) as client:
        yield client
