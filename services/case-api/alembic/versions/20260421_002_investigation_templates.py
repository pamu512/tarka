"""Investigation templates + case SLA / owner fields (Marble #56).

Revision ID: 20260421_002
Revises: 20260402_001
Create Date: 2026-04-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260421_002"
down_revision: str | None = "20260402_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("apply_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_investigation_templates_tenant_slug"),
    )
    op.create_index(
        "ix_investigation_templates_tenant_id",
        "investigation_templates",
        ["tenant_id"],
        unique=False,
    )

    op.add_column(
        "investigation_cases", sa.Column("default_owner", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "investigation_cases", sa.Column("sla_hours_override", sa.Integer(), nullable=True)
    )
    op.add_column(
        "investigation_cases",
        sa.Column("applied_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investigation_cases", "applied_template_id")
    op.drop_column("investigation_cases", "sla_hours_override")
    op.drop_column("investigation_cases", "default_owner")
    op.drop_index("ix_investigation_templates_tenant_id", table_name="investigation_templates")
    op.drop_table("investigation_templates")
