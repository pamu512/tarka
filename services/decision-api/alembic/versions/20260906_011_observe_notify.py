"""observe_notify inbox (P-enf1).

Revision ID: 20260906_011
Revises: 20260905_010
Create Date: 2026-09-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_011"
down_revision: Union[str, None] = "20260905_010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observe_notify",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("href", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "type",
            "subject_id",
            name="uq_observe_notify_dedupe",
        ),
    )
    op.create_index(
        op.f("ix_observe_notify_tenant_id"),
        "observe_notify",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_observe_notify_tenant_id"), table_name="observe_notify")
    op.drop_table("observe_notify")
