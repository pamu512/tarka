"""OSINT FinOps audit rows (estimated savings on cache/budget short-circuits).

Revision ID: 20260510_002
Revises: 20260506_001
Create Date: 2026-05-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260510_002"
down_revision: str | None = "20260506_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "osint_finops_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("vendor_key", sa.String(length=64), nullable=False),
        sa.Column("skip_reason", sa.String(length=48), nullable=False),
        sa.Column("estimated_savings_usd", sa.Float(), nullable=False),
        sa.Column("detail_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_osint_finops_audit_created_at"), "osint_finops_audit", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_osint_finops_audit_skip_reason"),
        "osint_finops_audit",
        ["skip_reason"],
        unique=False,
    )
    op.create_index(
        op.f("ix_osint_finops_audit_tenant_id"), "osint_finops_audit", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_osint_finops_audit_vendor_key"), "osint_finops_audit", ["vendor_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_osint_finops_audit_vendor_key"), table_name="osint_finops_audit")
    op.drop_index(op.f("ix_osint_finops_audit_tenant_id"), table_name="osint_finops_audit")
    op.drop_index(op.f("ix_osint_finops_audit_skip_reason"), table_name="osint_finops_audit")
    op.drop_index(op.f("ix_osint_finops_audit_created_at"), table_name="osint_finops_audit")
    op.drop_table("osint_finops_audit")
