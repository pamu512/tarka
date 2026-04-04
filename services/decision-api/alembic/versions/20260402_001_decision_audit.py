"""Initial decision_audit table.

Revision ID: 20260402_001
Revises:
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260402_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_hits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_audit_entity_id"), "decision_audit", ["entity_id"], unique=False)
    op.create_index(op.f("ix_decision_audit_tenant_id"), "decision_audit", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_decision_audit_trace_id"), "decision_audit", ["trace_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_audit_trace_id"), table_name="decision_audit")
    op.drop_index(op.f("ix_decision_audit_tenant_id"), table_name="decision_audit")
    op.drop_index(op.f("ix_decision_audit_entity_id"), table_name="decision_audit")
    op.drop_table("decision_audit")
