"""Inference audit log table with ClickHouse sync columns.

Revision ID: 20260509_008
Revises: 20260507_007
Create Date: 2026-05-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260509_008"
down_revision: Union[str, None] = "20260507_007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inference_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_hits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column(
            "sync_failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("sync_next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_inference_logs_entity_id"),
        "inference_logs",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inference_logs_sync_next_retry_at"),
        "inference_logs",
        ["sync_next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inference_logs_sync_status"),
        "inference_logs",
        ["sync_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inference_logs_tenant_id"),
        "inference_logs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inference_logs_trace_id"), "inference_logs", ["trace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_inference_logs_trace_id"), table_name="inference_logs")
    op.drop_index(op.f("ix_inference_logs_tenant_id"), table_name="inference_logs")
    op.drop_index(op.f("ix_inference_logs_sync_status"), table_name="inference_logs")
    op.drop_index(
        op.f("ix_inference_logs_sync_next_retry_at"), table_name="inference_logs"
    )
    op.drop_index(op.f("ix_inference_logs_entity_id"), table_name="inference_logs")
    op.drop_table("inference_logs")
