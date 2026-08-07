"""marketplace promo redemptions + seller integrity — durable boards (Track B3)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_008"
down_revision = "20260807_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_promo_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("coupon_code", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("device_id", sa.String(length=256), nullable=True),
        sa.Column("order_total", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("ip_hint", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "trace_id",
            name="uq_marketplace_promo_redemption_trace",
        ),
    )
    op.create_index(
        "ix_marketplace_promo_redemptions_tenant_id",
        "marketplace_promo_redemptions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_marketplace_promo_redemptions_coupon_code",
        "marketplace_promo_redemptions",
        ["coupon_code"],
    )
    op.create_index(
        "ix_marketplace_promo_redemptions_user_id",
        "marketplace_promo_redemptions",
        ["user_id"],
    )
    op.create_index(
        "ix_marketplace_promo_redemptions_device_id",
        "marketplace_promo_redemptions",
        ["device_id"],
    )
    op.create_index(
        "ix_marketplace_promo_redemptions_redeemed_at",
        "marketplace_promo_redemptions",
        ["redeemed_at"],
    )

    op.create_table(
        "marketplace_seller_integrity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("seller_id", sa.String(length=256), nullable=False),
        sa.Column("successful_deliveries", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("store_slug", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("avg_rating", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "seller_id",
            name="uq_marketplace_seller_integrity",
        ),
    )
    op.create_index(
        "ix_marketplace_seller_integrity_tenant_id",
        "marketplace_seller_integrity",
        ["tenant_id"],
    )
    op.create_index(
        "ix_marketplace_seller_integrity_seller_id",
        "marketplace_seller_integrity",
        ["seller_id"],
    )
    op.create_index(
        "ix_marketplace_seller_integrity_updated_at",
        "marketplace_seller_integrity",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_table("marketplace_seller_integrity")
    op.drop_table("marketplace_promo_redemptions")
