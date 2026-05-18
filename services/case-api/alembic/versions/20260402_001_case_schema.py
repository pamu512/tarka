"""Initial case-api schema (cases, comments, SAR, label drafts, disputes).

Revision ID: 20260402_001
Revises:
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260402_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investigation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("assigned_team", sa.String(length=128), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
    )
    op.create_index(
        op.f("ix_investigation_cases_entity_id"), "investigation_cases", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_investigation_cases_tenant_id"), "investigation_cases", ["tenant_id"], unique=False
    )

    op.create_table(
        "case_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["investigation_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "sar_filings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("report_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("xml_content", sa.Text(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["investigation_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "investigation_label_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("analyst_id", sa.String(length=256), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=512), nullable=True),
        sa.Column("y_label", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
    )
    op.create_index(
        op.f("ix_investigation_label_drafts_analyst_id"),
        "investigation_label_drafts",
        ["analyst_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_label_drafts_entity_id"),
        "investigation_label_drafts",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_label_drafts_tenant_id"),
        "investigation_label_drafts",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_label_drafts_trace_id"),
        "investigation_label_drafts",
        ["trace_id"],
        unique=False,
    )

    op.create_table(
        "disputes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("dispute_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("merchant_id", sa.String(length=256), nullable=True),
        sa.Column("card_network", sa.String(length=32), nullable=True),
        sa.Column("original_decision", sa.String(length=16), nullable=True),
        sa.Column("original_score", sa.Float(), nullable=True),
        sa.Column("original_rule_hits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("original_ml_score", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "filed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["case_id"], ["investigation_cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_disputes_entity_id"), "disputes", ["entity_id"], unique=False)
    op.create_index(op.f("ix_disputes_tenant_id"), "disputes", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_disputes_trace_id"), "disputes", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_disputes_trace_id"), table_name="disputes")
    op.drop_index(op.f("ix_disputes_tenant_id"), table_name="disputes")
    op.drop_index(op.f("ix_disputes_entity_id"), table_name="disputes")
    op.drop_table("disputes")
    op.drop_index(
        op.f("ix_investigation_label_drafts_trace_id"), table_name="investigation_label_drafts"
    )
    op.drop_index(
        op.f("ix_investigation_label_drafts_tenant_id"), table_name="investigation_label_drafts"
    )
    op.drop_index(
        op.f("ix_investigation_label_drafts_entity_id"), table_name="investigation_label_drafts"
    )
    op.drop_index(
        op.f("ix_investigation_label_drafts_analyst_id"), table_name="investigation_label_drafts"
    )
    op.drop_table("investigation_label_drafts")
    op.drop_table("sar_filings")
    op.drop_table("case_comments")
    op.drop_index(op.f("ix_investigation_cases_tenant_id"), table_name="investigation_cases")
    op.drop_index(op.f("ix_investigation_cases_entity_id"), table_name="investigation_cases")
    op.drop_table("investigation_cases")
