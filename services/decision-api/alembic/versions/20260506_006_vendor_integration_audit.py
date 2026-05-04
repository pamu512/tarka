"""vendor_integration_audit: raw vendor HTTP payloads + latency (Audit Plane).

Revision ID: 20260506_006
Revises: 20260505_005
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260506_006"
down_revision: Union[str, None] = "20260505_005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendor_integration_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("vendor_id", sa.String(length=128), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vendor_integration_audit_trace_id"), "vendor_integration_audit", ["trace_id"], unique=False)
    op.create_index(op.f("ix_vendor_integration_audit_tenant_id"), "vendor_integration_audit", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_vendor_integration_audit_entity_id"), "vendor_integration_audit", ["entity_id"], unique=False)
    op.create_index(op.f("ix_vendor_integration_audit_vendor_id"), "vendor_integration_audit", ["vendor_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_vendor_integration_audit_vendor_id"), table_name="vendor_integration_audit")
    op.drop_index(op.f("ix_vendor_integration_audit_entity_id"), table_name="vendor_integration_audit")
    op.drop_index(op.f("ix_vendor_integration_audit_tenant_id"), table_name="vendor_integration_audit")
    op.drop_index(op.f("ix_vendor_integration_audit_trace_id"), table_name="vendor_integration_audit")
    op.drop_table("vendor_integration_audit")
