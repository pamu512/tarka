"""SAR intent investigative notes (HTML) for analyst workspace.

Revision ID: 20260508_007
Revises: 20260507_006
Create Date: 2026-05-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260508_007"
down_revision: str | None = "20260507_006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sar_filing_intents",
        sa.Column(
            "investigative_notes_html", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
    )


def downgrade() -> None:
    op.drop_column("sar_filing_intents", "investigative_notes_html")
