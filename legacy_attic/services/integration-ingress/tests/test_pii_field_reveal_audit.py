"""Unit tests for PII field reveal audit helpers (Prompt 177)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "pii_field_reveal_audit.py"
_spec = importlib.util.spec_from_file_location("pii_field_reveal_audit", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["pii_field_reveal_audit"] = _mod
_spec.loader.exec_module(_mod)


def test_masked_preview_email() -> None:
    assert _mod.masked_preview("alex@example.com", field_kind="email") == "al***@example.com"


def test_fingerprint_stable() -> None:
    a = _mod.fingerprint_value("secret")
    b = _mod.fingerprint_value("secret")
    assert a == b
    assert len(a) == 32
