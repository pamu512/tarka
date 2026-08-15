"""create_all on the shared fraud DB must not emit cases / audit_logs."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from audit_tables import ORCH_AUDIT_CREATE_TABLES  # noqa: E402


def test_shared_fraud_create_all_skips_case_tables() -> None:
    assert "tarka_outbox" in ORCH_AUDIT_CREATE_TABLES
    assert "decisions" in ORCH_AUDIT_CREATE_TABLES
    assert "cases" not in ORCH_AUDIT_CREATE_TABLES
    assert "audit_logs" not in ORCH_AUDIT_CREATE_TABLES
