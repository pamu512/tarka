"""backtest_runs: durable warehouse rule backtest jobs.

Revision ID: 20260505_005
Revises: 20260504_004
Create Date: 2026-05-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260505_005"
down_revision: Union[str, None] = "20260504_004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("window_start", sa.String(length=32), nullable=False),
        sa.Column("window_end", sa.String(length=32), nullable=False),
        sa.Column("rule_pack_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("rule_pack_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analytics_table", sa.String(length=128), nullable=False),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtest_runs_tenant_id"), "backtest_runs", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_backtest_runs_rule_pack_fingerprint_sha256"),
        "backtest_runs",
        ["rule_pack_fingerprint_sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_backtest_runs_rule_pack_fingerprint_sha256"), table_name="backtest_runs")
    op.drop_index(op.f("ix_backtest_runs_tenant_id"), table_name="backtest_runs")
    op.drop_table("backtest_runs")
