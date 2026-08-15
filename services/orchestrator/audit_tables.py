"""Tables orchestrator may create_all on the shared fraud Postgres.

``cases`` / ``audit_logs`` belong to shared-core. Dumping Base.metadata onto
the desk DB would create a colliding ``cases`` from tarka_shared.audit_trail.
``decisions`` is the shared timeline table (same columns as view_case_timeline).
"""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.schema import Table

ORCH_AUDIT_CREATE_TABLES = frozenset(
    {
        "decisions",
        "tarka_outbox",
        "tarka_label_dlq",
        "normalized_labels",
        "operational_signals",
        "orchestrator_poll_state",
        "lifecycle_cases",
        "case_history",
        "ai_tool_logs",
    }
)


def orchestrator_audit_tables() -> list[Table]:
    from tarka_shared.database.session import Base

    return [t for t in Base.metadata.sorted_tables if t.name in ORCH_AUDIT_CREATE_TABLES]


def create_orchestrator_audit_tables(sync_conn: Connection) -> None:
    from tarka_shared.database.session import Base

    tables = orchestrator_audit_tables()
    if tables:
        Base.metadata.create_all(sync_conn, tables=tables)
