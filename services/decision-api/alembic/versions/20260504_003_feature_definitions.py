"""feature_definitions for durable feature-store metadata.

Revision ID: 20260504_003
Revises: 20260503_002
Create Date: 2026-05-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260504_003"
down_revision: Union[str, None] = "20260503_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "ddl_status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("clickhouse_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            "version",
            name="uq_feature_definitions_tenant_name_version",
        ),
        sa.CheckConstraint(
            "ddl_status IN ('pending', 'applied', 'failed')",
            name="ck_feature_definitions_ddl_status",
        ),
    )
    op.create_index(
        op.f("ix_feature_definitions_tenant_id"),
        "feature_definitions",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_feature_definitions_tenant_id"), table_name="feature_definitions"
    )
    op.drop_table("feature_definitions")
