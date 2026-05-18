"""Unit tests for synthetic identity detectors (Prompt 181)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "integration_ingress"
    / "synthetic_identity_detectors.py"
)
_spec = importlib.util.spec_from_file_location("synthetic_identity_detectors", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["synthetic_identity_detectors"] = _mod
_spec.loader.exec_module(_mod)


def test_payload_has_flagged_users() -> None:
    payload = _mod.build_synthetic_identity_payload(tenant_id="demo", limit=30)
    assert payload["tenant_id"] == "demo"
    assert payload["summary"]["scanned_users"] == 30
    assert payload["summary"]["flagged_users"] >= 1
    flagged = [u for u in payload["users"] if u["is_synthetic_identity"]]
    assert len(flagged) == payload["summary"]["flagged_users"]


def test_triple_combo_marks_synthetic() -> None:
    payload = _mod.build_synthetic_identity_payload(tenant_id="demo", limit=50, flag_score=95)
    triple = [u for u in payload["users"] if "synthetic_identity_triple" in u.get("combo_flags", [])]
    assert triple
    assert all(u["is_synthetic_identity"] for u in triple)
