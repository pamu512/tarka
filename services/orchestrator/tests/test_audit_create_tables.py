"""create_all on the shared fraud DB must not emit cases / audit_logs."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from audit_tables import (  # noqa: E402
    ORCH_AUDIT_CREATE_TABLES,
    create_orchestrator_audit_tables,
    orchestrator_audit_tables,
)


def test_shared_fraud_create_all_skips_case_tables() -> None:
    assert "tarka_outbox" in ORCH_AUDIT_CREATE_TABLES
    assert "decisions" in ORCH_AUDIT_CREATE_TABLES
    assert "cases" not in ORCH_AUDIT_CREATE_TABLES
    assert "audit_logs" not in ORCH_AUDIT_CREATE_TABLES
    names = {t.name for t in orchestrator_audit_tables("postgresql")}
    assert "cases" not in names
    assert "audit_logs" not in names


def test_sqlite_create_all_includes_shared_audit_tables() -> None:
    from sqlalchemy import create_engine, inspect

    import models.cases  # noqa: F401
    import models.decision  # noqa: F401
    import models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401

    names = {t.name for t in orchestrator_audit_tables("sqlite")}
    assert "cases" in names
    assert "audit_logs" in names
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        create_orchestrator_audit_tables(conn)
    created = set(inspect(engine).get_table_names())
    assert {"cases", "audit_logs", "tarka_outbox", "lifecycle_cases"} <= created
