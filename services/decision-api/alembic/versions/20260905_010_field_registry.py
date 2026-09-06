"""field_registry overlay + field_maps (P-reg1).

Revision ID: 20260905_010
Revises: 20260510_009
Create Date: 2026-09-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_010"
down_revision: Union[str, None] = "20260510_009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "field_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
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
            "tenant_id",
            "name",
            name="uq_field_registry_tenant_name",
        ),
    )
    op.create_index(
        op.f("ix_field_registry_tenant_id"),
        "field_registry",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "field_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("buyer_key", sa.String(length=256), nullable=False),
        sa.Column("registry_name", sa.String(length=128), nullable=False),
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
            "tenant_id",
            "buyer_key",
            name="uq_field_maps_tenant_buyer",
        ),
    )
    op.create_index(
        op.f("ix_field_maps_tenant_id"),
        "field_maps",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_field_maps_tenant_id"), table_name="field_maps")
    op.drop_table("field_maps")
    op.drop_index(op.f("ix_field_registry_tenant_id"), table_name="field_registry")
    op.drop_table("field_registry")
