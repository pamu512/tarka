"""Revision ID: 20260831_011
Revises: 20260831_010
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_011"
down_revision: str | None = "20260831_010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("leftover_promote_acks"):
        return
    op.create_table(
        "leftover_promote_acks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("draft_id", sa.String(length=256), nullable=False),
        sa.Column("acked_by", sa.String(length=256), nullable=False),
        sa.Column(
            "acked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "draft_id", name="uq_leftover_promote_acks_tenant_draft"),
    )
    op.create_index(
        op.f("ix_leftover_promote_acks_tenant_id"),
        "leftover_promote_acks",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("leftover_promote_acks"):
        return
    op.drop_index(op.f("ix_leftover_promote_acks_tenant_id"), table_name="leftover_promote_acks")
    op.drop_table("leftover_promote_acks")
