"""Durable evaluate idempotency on authoritative decision audits.

Revision ID: 20260724_010
Revises: 20260510_009
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_010"
down_revision: Union[str, None] = "20260510_009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("decision_audit") as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_key", sa.String(length=512), nullable=True),
        )
        batch_op.add_column(
            sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "idempotency_response",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
        batch_op.create_unique_constraint(
            "uq_decision_audit_tenant_idempotency_key",
            ["tenant_id", "idempotency_key"],
        )
    op.create_index(
        "ix_decision_audit_idempotency_key",
        "decision_audit",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_decision_audit_idempotency_key", table_name="decision_audit")
    with op.batch_alter_table("decision_audit") as batch_op:
        batch_op.drop_constraint(
            "uq_decision_audit_tenant_idempotency_key",
            type_="unique",
        )
        batch_op.drop_column("idempotency_response")
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("idempotency_key")
