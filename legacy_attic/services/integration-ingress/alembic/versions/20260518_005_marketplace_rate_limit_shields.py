"""Per SDK API key rate limit shields (Prompt 176)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260518_005"
down_revision = "20260518_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_sdk_api_keys",
        sa.Column("rate_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "marketplace_sdk_api_keys",
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default="600"),
    )
    op.add_column(
        "marketplace_sdk_api_keys",
        sa.Column("rate_limit_burst", sa.Integer(), nullable=False, server_default="50"),
    )


def downgrade() -> None:
    op.drop_column("marketplace_sdk_api_keys", "rate_limit_burst")
    op.drop_column("marketplace_sdk_api_keys", "rate_limit_rpm")
    op.drop_column("marketplace_sdk_api_keys", "rate_limit_enabled")
