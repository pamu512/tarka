"""rule_approvals for durable maker–checker audit tokens (SR-11).

Revision ID: 20260504_004
Revises: 20260504_003
Create Date: 2026-05-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260504_004"
down_revision: Union[str, None] = "20260504_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_name", sa.String(length=120), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.String(length=256), nullable=False),
        sa.Column("audit_token", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_token", name="uq_rule_approvals_audit_token"),
    )
    op.create_index(
        op.f("ix_rule_approvals_fingerprint_sha256"),
        "rule_approvals",
        ["fingerprint_sha256"],
        unique=False,
    )
    op.create_index(op.f("ix_rule_approvals_pack_name"), "rule_approvals", ["pack_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rule_approvals_pack_name"), table_name="rule_approvals")
    op.drop_index(op.f("ix_rule_approvals_fingerprint_sha256"), table_name="rule_approvals")
    op.drop_table("rule_approvals")
