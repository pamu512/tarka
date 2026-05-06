"""Dispute provider deadlines + idempotent external reprocess ledger (#60 / epic #58).

Revision ID: 20260421_003
Revises: 20260421_002
Create Date: 2026-04-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260421_003"
down_revision: str | None = "20260421_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "disputes",
        sa.Column("provider_response_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "disputes",
        sa.Column("external_reprocess_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "disputes",
        sa.Column("last_external_reprocess_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "dispute_reprocess_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispute_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("response_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dispute_id", "idempotency_key", name="uq_dispute_reprocess_idempotency"
        ),
    )
    op.create_index(
        "ix_dispute_reprocess_ledger_tenant_id",
        "dispute_reprocess_ledger",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dispute_reprocess_ledger_tenant_id", table_name="dispute_reprocess_ledger")
    op.drop_table("dispute_reprocess_ledger")
    op.drop_column("disputes", "last_external_reprocess_at")
    op.drop_column("disputes", "external_reprocess_count")
    op.drop_column("disputes", "provider_response_deadline_at")
