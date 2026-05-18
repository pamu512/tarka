"""Unit tests for KYC handover (Prompt 186)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "kyc_handover.py"
_spec = importlib.util.spec_from_file_location("kyc_handover", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["kyc_handover"] = _mod
_spec.loader.exec_module(_mod)


def test_board_lists_needs_more_id() -> None:
    board = _mod.build_kyc_handover_board(tenant_id="demo")
    assert board["summary"]["needs_more_id_count"] >= 1
    assert any(c["kyc_status"] == "needs_more_id" for c in board["cases"])


def test_send_email_updates_handover() -> None:
    _mod._SENT_BY_CASE.clear()
    result = _mod.send_kyc_id_request_email(
        tenant_id="demo", case_id="c1", analyst_note="Please upload ID"
    )
    assert result["ok"] is True
    assert result["email"]["to"]
    assert result["handover"]["handover_status"] == "email_sent"
    board = _mod.build_kyc_handover_board(tenant_id="demo", case_id="c1")
    assert board["cases"][0]["email_sent_at"] is not None


def test_send_rejects_verified_case() -> None:
    result = _mod.send_kyc_id_request_email(tenant_id="demo", case_id="c3")
    assert result["ok"] is False
    assert result["error"] == "kyc_not_pending"
