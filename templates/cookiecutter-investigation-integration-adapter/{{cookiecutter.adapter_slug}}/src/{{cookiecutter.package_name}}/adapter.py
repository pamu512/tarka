"""
Map customer Case / Graph / Decision HTTP APIs to shapes expected by investigation-agent tools.

This module is a stub: implement real clients, auth, pagination, and field mapping here (or split into
submodules). Keep `INTEGRATION_PROFILE_ID` in agent config aligned with profile `{{ cookiecutter.integration_profile_id }}`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

INTEGRATION_PROFILE_ID = "{{ cookiecutter.integration_profile_id }}"


def _base_url(env_var: str, default: str = "") -> str:
    return (os.environ.get(env_var) or default).rstrip("/")


def http_client(timeout_s: float = 30.0) -> httpx.Client:
    """Shared sync client; switch to AsyncClient if the adapter is async end-to-end."""
    return httpx.Client(timeout=timeout_s)


def example_health_probe() -> dict[str, Any]:
    """Replace with a real lightweight call to the customer API (e.g. token + /status)."""
    return {"profile": INTEGRATION_PROFILE_ID, "status": "stub"}
