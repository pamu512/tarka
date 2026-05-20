"""Unit tests for marketplace SDK API key helpers (Prompt 174)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "integration_ingress"
    / "marketplace_sdk_api_keys.py"
)
_spec = importlib.util.spec_from_file_location("marketplace_sdk_api_keys", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_generate_and_hash_secret() -> None:
    secret = _mod.generate_sdk_api_secret()
    assert secret.startswith("tarka_mkt_")
    h1 = _mod._hash_secret(secret)
    h2 = _mod._hash_secret(secret)
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_scopes_defaults() -> None:
    scopes = _mod.normalize_scopes(None, "sdk-python")
    assert "evaluate" in scopes


def test_validate_platform_unknown() -> None:
    try:
        _mod.validate_platform("not-a-sdk")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
