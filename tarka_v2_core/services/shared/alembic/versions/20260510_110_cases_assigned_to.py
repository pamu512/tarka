"""Add ``assigned_to`` to ``cases`` (mutable with ``status`` under immutability trigger).

Revision ID: 110_cases_assigned_to
Revises: 109_evidence_locker
Create Date: 2026-05-10

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "110_cases_assigned_to"
down_revision: Union[str, None] = "109_evidence_locker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "cases" not in inspect(bind).get_table_names():
        raise RuntimeError("cases table is missing")
    if bind.dialect.name == "postgresql":
        col_type = sa.VARCHAR(128)
    else:
        col_type = sa.String(128)
    op.add_column("cases", sa.Column("assigned_to", col_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "cases" not in inspect(bind).get_table_names():
        return
    op.drop_column("cases", "assigned_to")
