"""Durable SAR transport intent rows (Mission 3 / SR-08).

Revision ID: 20260504_005
Revises: 20260421_004
Create Date: 2026-05-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260504_005"
down_revision: str | None = "20260421_004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sar_filing_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("filing_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audit_trail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["investigation_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'failed')",
            name="ck_sar_filing_intents_status",
        ),
    )
    op.create_index(
        op.f("ix_sar_filing_intents_tenant_id"), "sar_filing_intents", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_sar_filing_intents_case_id"), "sar_filing_intents", ["case_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sar_filing_intents_case_id"), table_name="sar_filing_intents")
    op.drop_index(op.f("ix_sar_filing_intents_tenant_id"), table_name="sar_filing_intents")
    op.drop_table("sar_filing_intents")
