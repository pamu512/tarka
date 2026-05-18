"""Evidence locker: ``cases`` graph snapshot, AI trace, raw signals ref.

Adds immutable-ingestion columns to the Shadow ``cases`` table
(:class:`tarka_shared.audit_trail.Case`).

Prerequisite: ``public.cases`` already exists (created by app ``create_all`` or prior DDL).

Gate (Postgres): ``deploy/scripts/gate_cases_evidence_columns_psql.sh``

Revision ID: 109_evidence_locker
Revises:
Create Date: 2026-05-10

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "109_evidence_locker"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "cases" not in inspect(bind).get_table_names():
        raise RuntimeError(
            "cases table is missing; create schema (e.g. app metadata.create_all) before this revision."
        )
    if bind.dialect.name == "postgresql":
        graph_type: sa.types.TypeEngine = postgresql.JSONB(astext_type=sa.Text())
        ref_type: sa.types.TypeEngine = postgresql.UUID(as_uuid=True)
    else:
        # SQLite (local alembic smoke): JSON + string UUID; production should use Postgres + psql gate.
        graph_type = sa.JSON()
        ref_type = sa.Uuid(as_uuid=True)

    op.add_column("cases", sa.Column("graph_snapshot", graph_type, nullable=True))
    op.add_column("cases", sa.Column("ai_trace", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("raw_signals_ref", ref_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "cases" not in inspect(bind).get_table_names():
        return
    op.drop_column("cases", "raw_signals_ref")
    op.drop_column("cases", "ai_trace")
    op.drop_column("cases", "graph_snapshot")
