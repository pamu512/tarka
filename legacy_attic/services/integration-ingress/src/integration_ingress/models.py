import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from integration_ingress.db import Base


class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    normalized: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_id", name="uq_integration_tenant_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_id: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="enabled", index=True)
    configured: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_connectivity_test: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketplaceWebhookLog(Base):
    """Outgoing Block (and related) signals POSTed to marketplace client callback URLs."""

    __tablename__ = "marketplace_webhook_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    signal: Mapped[str] = mapped_column(String(32), default="block", index=True)
    decision: Mapped[str] = mapped_column(String(32), default="BLOCK", index=True)
    entity_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    callback_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_preview: Mapped[str] = mapped_column(Text, default="")
    attempts_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketplaceSdkApiKey(Base):
    """Tenant-scoped API keys for Marketplace SDK packages (evaluate / ingest / attestation)."""

    __tablename__ = "marketplace_sdk_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    key_prefix: Mapped[str] = mapped_column(String(64), index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer(), default=600)
    rate_limit_burst: Mapped[int] = mapped_column(Integer(), default=50)


class IntegrationSecret(Base):
    __tablename__ = "integration_secrets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_id", name="uq_secret_tenant_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_id: Mapped[str] = mapped_column(String(128), index=True)
    key_id: Mapped[str] = mapped_column(String(64), default="v1", index=True)
    wrapped_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IntegrationOperation(Base):
    __tablename__ = "integration_operations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_id", "action", "idempotency_key", name="uq_integration_operation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    provider_id: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    response_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KMSRotationJob(Base):
    __tablename__ = "kms_rotation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    old_key_id: Mapped[str] = mapped_column(String(128))
    new_key_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    total_secrets: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    rotated: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    batch_size: Mapped[int] = mapped_column(Integer, default=100)
    checkpoint_offset: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KMSRotationFailure(Base):
    __tablename__ = "kms_rotation_failures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    key_id: Mapped[str] = mapped_column(String(128))
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SanctionsScreeningLog(Base):
    """Durable audit row for every sanctions adapter request (SR-17)."""

    __tablename__ = "sanctions_screening_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    match_found: Mapped[bool] = mapped_column(Boolean(), nullable=False, index=True)
    match_details: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class OsintFinopsAudit(Base):
    """Audit-plane row for OSINT FinOps short-circuits (cache / budget); stores estimated avoided vendor cost."""

    __tablename__ = "osint_finops_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skip_reason: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    estimated_savings_usd: Mapped[float] = mapped_column(Float(), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class PiiFieldRevealAudit(Base):
    """Immutable audit row when an analyst reveals or hides a masked PII field in the UI."""

    __tablename__ = "pii_field_reveal_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(16), index=True)
    field_kind: Mapped[str] = mapped_column(String(32))
    field_path: Mapped[str] = mapped_column(String(256))
    context_type: Mapped[str] = mapped_column(String(64))
    context_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    value_fingerprint: Mapped[str] = mapped_column(String(64))
    masked_preview: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ComplianceResidencyAudit(Base):
    """Audit-plane row when an outbound vendor call is blocked for data residency (pre-socket)."""

    __tablename__ = "compliance_residency_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vendor_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_region: Mapped[str] = mapped_column(String(16), nullable=False)
    vendor_region: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_url_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
