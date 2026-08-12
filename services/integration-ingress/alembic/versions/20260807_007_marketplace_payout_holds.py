"""marketplace_payout_holds — durable evaluate/automation payout holds (Marketplace P0)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_007"
down_revision = "20260518_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_payout_holds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("payout_id", sa.String(length=256), nullable=False),
        sa.Column("entity_id", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("hold_reason", sa.String(length=512), nullable=True),
        sa.Column("held_by", sa.String(length=64), nullable=True),
        sa.Column("decision_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("mule_score", sa.Float(), nullable=True),
        sa.Column(
            "held_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scheduled_release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "payout_id", name="uq_marketplace_payout_hold"),
    )
    op.create_index(
        "ix_marketplace_payout_holds_tenant_id", "marketplace_payout_holds", ["tenant_id"]
    )
    op.create_index(
        "ix_marketplace_payout_holds_payout_id", "marketplace_payout_holds", ["payout_id"]
    )
    op.create_index(
        "ix_marketplace_payout_holds_entity_id", "marketplace_payout_holds", ["entity_id"]
    )
    op.create_index("ix_marketplace_payout_holds_status", "marketplace_payout_holds", ["status"])
    op.create_index(
        "ix_marketplace_payout_holds_trace_id", "marketplace_payout_holds", ["trace_id"]
    )
    op.create_index("ix_marketplace_payout_holds_held_at", "marketplace_payout_holds", ["held_at"])


def downgrade() -> None:
    op.drop_table("marketplace_payout_holds")
