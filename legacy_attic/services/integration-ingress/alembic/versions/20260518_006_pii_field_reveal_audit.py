"""pii_field_reveal_audit — audit trail for analyst PII reveal/hide toggles (Prompt 177)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260518_006"
down_revision = "20260518_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pii_field_reveal_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("field_kind", sa.String(length=32), nullable=False),
        sa.Column("field_path", sa.String(length=256), nullable=False),
        sa.Column("context_type", sa.String(length=64), nullable=False),
        sa.Column("context_id", sa.String(length=256), nullable=True),
        sa.Column("value_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("masked_preview", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pii_field_reveal_audit_tenant_id", "pii_field_reveal_audit", ["tenant_id"])
    op.create_index("ix_pii_field_reveal_audit_action", "pii_field_reveal_audit", ["action"])
    op.create_index("ix_pii_field_reveal_audit_created_at", "pii_field_reveal_audit", ["created_at"])


def downgrade() -> None:
    op.drop_table("pii_field_reveal_audit")
