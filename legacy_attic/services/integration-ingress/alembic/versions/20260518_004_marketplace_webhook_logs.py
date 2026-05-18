"""marketplace_webhook_logs — outgoing Block signals to marketplace clients (Prompt 175)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260518_004"
down_revision = "20260518_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_webhook_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("signal", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=256), nullable=True),
        sa.Column("user_id", sa.String(length=256), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("callback_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_preview", sa.Text(), nullable=False),
        sa.Column("attempts_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_webhook_logs_tenant_id", "marketplace_webhook_logs", ["tenant_id"])
    op.create_index("ix_marketplace_webhook_logs_status", "marketplace_webhook_logs", ["status"])
    op.create_index("ix_marketplace_webhook_logs_created_at", "marketplace_webhook_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("marketplace_webhook_logs")
