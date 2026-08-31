"""Revision ID: 20260831_010
Revises: 20260831_009
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_010"
down_revision: str | None = "20260831_009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = (
    ("claimed_by", sa.String(length=256)),
    ("claimed_at", sa.DateTime(timezone=True)),
    ("last_outcome", sa.String(length=32)),
    ("last_act", sa.String(length=32)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("investigation_cases"):
        return
    existing = {c["name"] for c in inspector.get_columns("investigation_cases")}
    for name, col_type in _COLS:
        if name not in existing:
            op.add_column("investigation_cases", sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("investigation_cases"):
        return
    existing = {c["name"] for c in inspector.get_columns("investigation_cases")}
    for name, _ in reversed(_COLS):
        if name in existing:
            op.drop_column("investigation_cases", name)
