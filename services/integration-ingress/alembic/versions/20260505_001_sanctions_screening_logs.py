"""Sanctions screening durable audit log (SR-17 / Tier-1).

Revision ID: 20260505_001
Revises:
Create Date: 2026-05-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260505_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS sanctions_matches"))
    op.create_table(
        "sanctions_screening_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_name", sa.String(length=512), nullable=False),
        sa.Column("match_found", sa.Boolean(), nullable=False),
        sa.Column("match_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sanctions_screening_logs_tenant_id"),
        "sanctions_screening_logs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sanctions_screening_logs_entity_name"),
        "sanctions_screening_logs",
        ["entity_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sanctions_screening_logs_match_found"),
        "sanctions_screening_logs",
        ["match_found"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sanctions_screening_logs_created_at"),
        "sanctions_screening_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sanctions_screening_logs_created_at"), table_name="sanctions_screening_logs")
    op.drop_index(op.f("ix_sanctions_screening_logs_match_found"), table_name="sanctions_screening_logs")
    op.drop_index(op.f("ix_sanctions_screening_logs_entity_name"), table_name="sanctions_screening_logs")
    op.drop_index(op.f("ix_sanctions_screening_logs_tenant_id"), table_name="sanctions_screening_logs")
    op.drop_table("sanctions_screening_logs")
