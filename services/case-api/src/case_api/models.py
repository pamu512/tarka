import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from case_api.db import Base


class Case(Base):
    __tablename__ = "investigation_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="open")
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    assigned_team: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    default_owner: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
    sla_hours_override: Mapped[int | None] = mapped_column(nullable=True, default=None)
    applied_template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    comments: Mapped[list["CaseComment"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class InvestigationTemplate(Base):
    """Tenant-scoped investigation template (Marble #56): apply_config drives case mutations + SLA hints."""

    __tablename__ = "investigation_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_investigation_templates_tenant_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    slug: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    apply_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CaseComment(Base):
    __tablename__ = "case_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="CASCADE")
    )
    author: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="comments")


class CaseView(Base):
    __tablename__ = "case_views"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_case_views_tenant_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SARFiling(Base):
    __tablename__ = "sar_filings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="CASCADE")
    )
    format: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    narrative: Mapped[str] = mapped_column(Text())
    report_data: Mapped[dict] = mapped_column(JSON, default=dict)
    xml_content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SarFiling(Base):
    """Durable SAR filing intent + regulatory state machine (FinCEN BSA E-Filing / SR-08)."""

    __tablename__ = "sar_filing_intents"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'PENDING_REVIEW','APPROVED','SFTP_QUEUED','TRANSMITTED','ACKNOWLEDGED','FAILED'"
            ")",
            name="ck_sar_filing_intents_status_v2",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="CASCADE"), index=True
    )
    sar_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sar_filings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_trail: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SarAuditLog(Base):
    """Immutable append-only log of SAR intent state transitions (compliance audit trail)."""

    __tablename__ = "sar_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sar_filing_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sar_filing_intents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stack_trace: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InvestigationLabelDraft(Base):
    """Analyst-scoped draft labels for investigation / replay workflows (not case workflow labels)."""

    __tablename__ = "investigation_label_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    analyst_id: Mapped[str] = mapped_column(String(256), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    y_label: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(128), default="analyst")
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    dispute_type: Mapped[str] = mapped_column(
        String(32)
    )  # "chargeback", "dispute", "fraud_claim", "unauthorized"
    status: Mapped[str] = mapped_column(
        String(32), default="filed"
    )  # filed, investigating, accepted, rejected, resolved
    reason_code: Mapped[str] = mapped_column(String(64), default="")
    amount: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    merchant_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    card_network: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # visa, mastercard, amex
    original_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_score: Mapped[float | None] = mapped_column(nullable=True)
    original_rule_hits: Mapped[list] = mapped_column(JSON, default=list)
    original_ml_score: Mapped[float | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # fraud_confirmed, false_positive, inconclusive
    resolution_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_response_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    external_reprocess_count: Mapped[int] = mapped_column(Integer(), default=0)
    last_external_reprocess_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DisputeReprocessLedger(Base):
    """Idempotent external reprocess attempts for dispute / refund ops (#60)."""

    __tablename__ = "dispute_reprocess_ledger"
    __table_args__ = (
        UniqueConstraint("dispute_id", "idempotency_key", name="uq_dispute_reprocess_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    response_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
