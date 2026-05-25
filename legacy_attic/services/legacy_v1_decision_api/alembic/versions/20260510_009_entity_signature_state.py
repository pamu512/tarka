"""Entity signature state (Postgres SOT for Redis fraud:tags hot cache).

Revision ID: 20260510_009
Revises: 20260509_008
Create Date: 2026-05-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260510_009"
down_revision: Union[str, None] = "20260509_008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_signature_state",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column(
            "tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "entity_id", name="pk_entity_signature_state"
        ),
    )
    op.create_index(
        "ix_entity_signature_state_updated_at",
        "entity_signature_state",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_signature_state_updated_at", table_name="entity_signature_state"
    )
    op.drop_table("entity_signature_state")
