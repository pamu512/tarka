"""Revision ID: 20260831_009
Revises: 20260621_008
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_009"
down_revision: str | None = "20260621_008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("audit_trail"):
        return
    op.create_table(
        "audit_trail",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_trail_tenant_id", "audit_trail", ["tenant_id"])
    op.create_index("ix_audit_trail_action", "audit_trail", ["action"])
    op.create_index("ix_audit_trail_resource_type", "audit_trail", ["resource_type"])
    op.create_index("ix_audit_trail_resource_id", "audit_trail", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_trail_resource_id", table_name="audit_trail")
    op.drop_index("ix_audit_trail_resource_type", table_name="audit_trail")
    op.drop_index("ix_audit_trail_action", table_name="audit_trail")
    op.drop_index("ix_audit_trail_tenant_id", table_name="audit_trail")
    op.drop_table("audit_trail")
