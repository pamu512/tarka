"""SAR regulatory state machine + immutable sar_audit_log (SR-08).

Revision ID: 20260507_006
Revises: 20260504_005
Create Date: 2026-05-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260507_006"
down_revision: str | None = "20260504_005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sar_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sar_filing_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sar_filing_intent_id"], ["sar_filing_intents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sar_audit_log_sar_filing_intent_id"),
        "sar_audit_log",
        ["sar_filing_intent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sar_audit_log_created_at"), "sar_audit_log", ["created_at"], unique=False
    )

    op.drop_constraint("ck_sar_filing_intents_status", "sar_filing_intents", type_="check")
    op.execute(
        """
        UPDATE sar_filing_intents SET status = CASE status
          WHEN 'pending' THEN 'PENDING_REVIEW'
          WHEN 'submitted' THEN 'TRANSMITTED'
          WHEN 'failed' THEN 'FAILED'
          ELSE 'FAILED'
        END
        """
    )
    op.add_column(
        "sar_filing_intents",
        sa.Column("sar_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sar_filing_intents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_sar_filing_intents_sar_artifact",
        "sar_filing_intents",
        "sar_filings",
        ["sar_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_sar_filing_intents_status_v2",
        "sar_filing_intents",
        "status IN ("
        "'PENDING_REVIEW','APPROVED','SFTP_QUEUED','TRANSMITTED','ACKNOWLEDGED','FAILED'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sar_filing_intents_status_v2", "sar_filing_intents", type_="check")
    op.drop_constraint(
        "fk_sar_filing_intents_sar_artifact", "sar_filing_intents", type_="foreignkey"
    )
    op.drop_column("sar_filing_intents", "updated_at")
    op.drop_column("sar_filing_intents", "sar_artifact_id")
    op.execute(
        """
        UPDATE sar_filing_intents SET status = CASE status
          WHEN 'PENDING_REVIEW' THEN 'pending'
          WHEN 'APPROVED' THEN 'pending'
          WHEN 'SFTP_QUEUED' THEN 'pending'
          WHEN 'TRANSMITTED' THEN 'submitted'
          WHEN 'ACKNOWLEDGED' THEN 'submitted'
          WHEN 'FAILED' THEN 'failed'
          ELSE 'failed'
        END
        """
    )
    op.create_check_constraint(
        "ck_sar_filing_intents_status",
        "sar_filing_intents",
        "status IN ('pending', 'submitted', 'failed')",
    )
    op.drop_index(op.f("ix_sar_audit_log_created_at"), table_name="sar_audit_log")
    op.drop_index(op.f("ix_sar_audit_log_sar_filing_intent_id"), table_name="sar_audit_log")
    op.drop_table("sar_audit_log")
