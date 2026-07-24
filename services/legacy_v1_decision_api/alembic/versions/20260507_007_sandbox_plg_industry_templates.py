"""PLG sandbox industry rule templates + merged bundle state (Audit Plane).

Revision ID: 20260507_007
Revises: 20260506_006
Create Date: 2026-05-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260507_007"
down_revision: Union[str, None] = "20260506_006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sandbox_industry_rule_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column(
            "bundle_key",
            sa.String(length=64),
            nullable=False,
            server_default="plg_industry_v1",
        ),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column(
            "visual_ast_pack", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "compiled_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "merged_pack_fingerprint_sha256", sa.String(length=64), nullable=False
        ),
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
        sa.UniqueConstraint(
            "template_key",
            "bundle_key",
            name="uq_sandbox_industry_templates_key_bundle",
        ),
    )
    op.create_index(
        op.f("ix_sandbox_industry_rule_templates_bundle_key"),
        "sandbox_industry_rule_templates",
        ["bundle_key"],
        unique=False,
    )

    op.create_table(
        "sandbox_plg_bundle_state",
        sa.Column("bundle_key", sa.String(length=64), nullable=False),
        sa.Column(
            "merged_pack_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("bundle_key", name="pk_sandbox_plg_bundle_state"),
    )


def downgrade() -> None:
    op.drop_table("sandbox_plg_bundle_state")
    op.drop_index(
        op.f("ix_sandbox_industry_rule_templates_bundle_key"),
        table_name="sandbox_industry_rule_templates",
    )
    op.drop_table("sandbox_industry_rule_templates")
