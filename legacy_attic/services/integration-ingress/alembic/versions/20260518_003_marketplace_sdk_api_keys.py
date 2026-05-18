"""marketplace_sdk_api_keys table (Prompt 174)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260518_003"
down_revision = "20260510_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_sdk_api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_marketplace_sdk_api_keys_tenant_id", "marketplace_sdk_api_keys", ["tenant_id"]
    )
    op.create_index(
        "ix_marketplace_sdk_api_keys_platform", "marketplace_sdk_api_keys", ["platform"]
    )
    op.create_index(
        "ix_marketplace_sdk_api_keys_key_prefix", "marketplace_sdk_api_keys", ["key_prefix"]
    )
    op.create_index(
        "ix_marketplace_sdk_api_keys_secret_hash", "marketplace_sdk_api_keys", ["secret_hash"]
    )
    op.create_index("ix_marketplace_sdk_api_keys_status", "marketplace_sdk_api_keys", ["status"])


def downgrade() -> None:
    op.drop_table("marketplace_sdk_api_keys")
