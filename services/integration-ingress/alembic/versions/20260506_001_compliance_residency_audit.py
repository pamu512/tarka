"""Compliance residency audit (pre-socket vendor blocks).

Revision ID: 20260506_001
Revises: 20260505_001
Create Date: 2026-05-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260506_001"
down_revision: str | None = "20260505_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_residency_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("vendor_key", sa.String(length=128), nullable=False),
        sa.Column("tenant_region", sa.String(length=16), nullable=False),
        sa.Column("vendor_region", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("request_url_preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_compliance_residency_audit_tenant_id"),
        "compliance_residency_audit",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compliance_residency_audit_vendor_key"),
        "compliance_residency_audit",
        ["vendor_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compliance_residency_audit_outcome"),
        "compliance_residency_audit",
        ["outcome"],
        unique=False,
    )
    op.create_index(
        op.f("ix_compliance_residency_audit_created_at"),
        "compliance_residency_audit",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_compliance_residency_audit_created_at"), table_name="compliance_residency_audit"
    )
    op.drop_index(
        op.f("ix_compliance_residency_audit_outcome"), table_name="compliance_residency_audit"
    )
    op.drop_index(
        op.f("ix_compliance_residency_audit_vendor_key"), table_name="compliance_residency_audit"
    )
    op.drop_index(
        op.f("ix_compliance_residency_audit_tenant_id"), table_name="compliance_residency_audit"
    )
    op.drop_table("compliance_residency_audit")
