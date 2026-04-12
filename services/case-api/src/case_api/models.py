import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from case_api.db import Base

_JSON_COL = JSON().with_variant(JSONB(), "postgresql")


class Case(Base):
    __tablename__ = "investigation_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="open")
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    assigned_team: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    labels: Mapped[list] = mapped_column(_JSON_COL, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    comments: Mapped[list["CaseComment"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class CaseComment(Base):
    __tablename__ = "case_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="comments")


class SARFiling(Base):
    __tablename__ = "sar_filings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_cases.id", ondelete="CASCADE"))
    format: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    narrative: Mapped[str] = mapped_column(Text())
    report_data: Mapped[dict] = mapped_column(_JSON_COL, default=dict)
    xml_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestigationLabelDraft(Base):
    """Analyst-scoped draft labels for investigation / replay workflows (not case workflow labels)."""

    __tablename__ = "investigation_label_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    analyst_id: Mapped[str] = mapped_column(String(256), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    y_label: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(128), default="analyst")
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation_cases.id", ondelete="SET NULL"), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    dispute_type: Mapped[str] = mapped_column(String(32))  # "chargeback", "dispute", "fraud_claim", "unauthorized"
    status: Mapped[str] = mapped_column(String(32), default="filed")  # filed, investigating, accepted, rejected, resolved
    reason_code: Mapped[str] = mapped_column(String(64), default="")
    amount: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    merchant_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    card_network: Mapped[str | None] = mapped_column(String(32), nullable=True)  # visa, mastercard, amex
    original_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_score: Mapped[float | None] = mapped_column(nullable=True)
    original_rule_hits: Mapped[list] = mapped_column(_JSON_COL, default=list)
    original_ml_score: Mapped[float | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)  # fraud_confirmed, false_positive, inconclusive
    resolution_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
