"""integration_outbox for CDC-style relay.

Revision ID: 20260503_002
Revises: 20260402_001
Create Date: 2026-05-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260503_002"
down_revision: Union[str, None] = "20260402_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_key", sa.String(length=512), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_integration_outbox_event_type"),
        "integration_outbox",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_outbox_aggregate_key"),
        "integration_outbox",
        ["aggregate_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_integration_outbox_aggregate_key"), table_name="integration_outbox"
    )
    op.drop_index(
        op.f("ix_integration_outbox_event_type"), table_name="integration_outbox"
    )
    op.drop_table("integration_outbox")
