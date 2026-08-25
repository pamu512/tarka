"""Smoke tests — run mock first: ``python scripts/integration_adapter_mock/server.py --port 18080``."""

from __future__ import annotations

import os

import pytest

from {{ cookiecutter.package_name }} import adapter


def test_integration_profile_constant() -> None:
    assert adapter.INTEGRATION_PROFILE_ID == "{{ cookiecutter.integration_profile_id }}"


@pytest.mark.skipif(
    os.environ.get("SKIP_ADAPTER_LIVE", "").strip() == "1",
    reason="SKIP_ADAPTER_LIVE=1",
)
def test_example_health_probe_against_mock() -> None:
    """Requires integration_adapter_mock on CASE_API_URL (default 127.0.0.1:18080)."""
    body = adapter.example_health_probe()
    assert body["profile"] == "{{ cookiecutter.integration_profile_id }}"
    assert body["status"] in ("ok", "degraded")
    assert "checks" in body
    if body["status"] == "ok":
        assert body["checks"]["case"]["ok"] is True
        assert body["checks"]["graph"]["ok"] is True
        assert body["checks"]["decision"]["ok"] is True
