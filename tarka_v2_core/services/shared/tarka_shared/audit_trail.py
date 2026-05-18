"""SQLAlchemy ORM models for audit-first Shadow persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .case_status import DEFAULT_CASE_STATUS
from .data.tenant_constants import DEFAULT_TENANT_ID
from .database.session import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_TENANT_ID,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    dataset_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DEFAULT_CASE_STATUS,
        server_default=text(f"'{DEFAULT_CASE_STATUS}'"),
    )
    #: Analyst / owner assignment (one of two columns mutable under ``triggers/immutable_cases.sql``).
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_optimization_manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duckdb_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    schema_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    #: Janus/Neo4j (or derived) topology snapshot for immutable evidence views.
    graph_snapshot: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    #: Serialized agent reasoning / tool trace for audit.
    ai_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Pointer to raw signal blob (object store row, bundle id, etc.).
    raw_signals_ref: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    leads: Mapped[list[Lead]] = relationship(
        "Lead", back_populates="case", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog", back_populates="case", cascade="all, delete-orphan"
    )
    workbench_pins: Mapped[CaseWorkbenchPins | None] = relationship(
        "CaseWorkbenchPins",
        back_populates="case",
        uselist=False,
        cascade="all, delete-orphan",
    )


class CaseShare(Base):
    """Allow ``viewer_case_id`` to include ``owner_case_id`` warehouse rows in scoped queries."""

    __tablename__ = "case_shares"
    __table_args__ = (
        UniqueConstraint("owner_case_id", "viewer_case_id", name="uq_case_share_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    viewer_case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )


class CaseWorkbenchPins(Base):
    """Pinned forensic cards for the workspace strip (persisted per case)."""

    __tablename__ = "case_workbench_pins"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    pins_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    case: Mapped[Case] = relationship("Case", back_populates="workbench_pins")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity_score: Mapped[float] = mapped_column(default=0.0)
    raw_data_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="OPEN", server_default=text("'OPEN'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped[Case] = relationship("Case", back_populates="leads")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    code_executed: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Shadow hypothesis rules that fired on this event (immutable promotion evidence).
    shadow_matches: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    case: Mapped[Case] = relationship("Case", back_populates="audit_logs")
