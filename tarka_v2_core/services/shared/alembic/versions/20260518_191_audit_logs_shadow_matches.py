"""Add ``audit_logs.shadow_matches`` JSONB for shadow hypothesis promotion evidence (Prompt 191).

Revision ID: 191_audit_logs_shadow_matches
Revises: 114_view_case_timeline
Create Date: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "191_audit_logs_shadow_matches"
down_revision: Union[str, None] = "114_view_case_timeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "audit_logs" not in inspect(bind).get_table_names():
        raise RuntimeError(
            "audit_logs table is missing; create schema before revision 191_audit_logs_shadow_matches."
        )
    if bind.dialect.name == "postgresql":
        col_type: sa.types.TypeEngine = postgresql.JSONB(astext_type=sa.Text())
    else:
        col_type = sa.JSON()
    op.add_column("audit_logs", sa.Column("shadow_matches", col_type, nullable=True))


def downgrade() -> None:
    op.drop_column("audit_logs", "shadow_matches")
