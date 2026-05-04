import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from decision_api.db import Base


class FeatureDefinitionDdlStatus(StrEnum):
    pending = "pending"
    applied = "applied"
    failed = "failed"


class AuditRecord(Base):
    __tablename__ = "decision_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    rule_hits: Mapped[list] = mapped_column(JSON, default=list)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureDefinition(Base):
    """Durable metadata for versioned feature-store definitions (ClickHouse DDL execution tracked via ddl_status)."""

    __tablename__ = "feature_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", "version", name="uq_feature_definitions_tenant_name_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    ddl_status: Mapped[FeatureDefinitionDdlStatus] = mapped_column(
        SAEnum(FeatureDefinitionDdlStatus, native_enum=False, length=16),
        nullable=False,
        default=FeatureDefinitionDdlStatus.pending,
        server_default=FeatureDefinitionDdlStatus.pending.value,
    )
    clickhouse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BacktestRunStatus(StrEnum):
    pending = "PENDING"
    running = "RUNNING"
    succeeded = "SUCCEEDED"
    failed_timeout = "FAILED_TIMEOUT"
    failed_error = "FAILED_ERROR"


class BacktestRun(Base):
    """Durable warehouse rule backtest job (keyset-streamed OLAP → Rust engine → aggregates)."""

    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[BacktestRunStatus] = mapped_column(
        SAEnum(BacktestRunStatus, native_enum=False, length=32),
        nullable=False,
        default=BacktestRunStatus.pending,
        server_default=BacktestRunStatus.pending.value,
    )
    window_start: Mapped[str] = mapped_column(String(32), nullable=False)
    window_end: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_pack_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_pack_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    analytics_table: Mapped[str] = mapped_column(String(128), nullable=False)
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RuleApproval(Base):
    """Persisted maker–checker approval row; audit_token is returned to clients (SR-11)."""

    __tablename__ = "rule_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    audit_token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VendorIntegrationAudit(Base):
    """Raw vendor HTTP payload + latency for the Audit Plane (Decision Engine consumes parsed signals separately)."""

    __tablename__ = "vendor_integration_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    vendor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
