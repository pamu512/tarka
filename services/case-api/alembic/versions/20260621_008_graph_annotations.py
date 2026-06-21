"""Revision ID: 20260621_008
Revises: 20260508_007
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260621_008"
down_revision: str | None = "20260508_007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_graph_annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("annotations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
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
        sa.ForeignKeyConstraint(["case_id"], ["investigation_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "case_id", name="uq_case_graph_annotations_tenant_case"),
    )
    op.create_index(
        op.f("ix_case_graph_annotations_tenant_id"),
        "case_graph_annotations",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_case_graph_annotations_case_id"),
        "case_graph_annotations",
        ["case_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_case_graph_annotations_case_id"), table_name="case_graph_annotations")
    op.drop_index(op.f("ix_case_graph_annotations_tenant_id"), table_name="case_graph_annotations")
    op.drop_table("case_graph_annotations")
