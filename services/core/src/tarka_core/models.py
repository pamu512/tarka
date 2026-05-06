"""Postgres ORM models shared by decision-api (Alembic) and analytics sync paths."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from tarka_core.sqla_base import Base


class InferenceSyncStatus(StrEnum):
    """Replication state from Audit (Postgres) to Analytics (ClickHouse)."""

    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


class InferenceLog(Base):
    """Durable inference / decision row in the audit plane; mirrored to ClickHouse by ``analytics.syncer``."""

    __tablename__ = "inference_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    rule_hits: Mapped[list[Any]] = mapped_column(JSON, default=list)
    payload_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[InferenceSyncStatus] = mapped_column(
        SAEnum(InferenceSyncStatus, native_enum=False, length=16),
        nullable=False,
        default=InferenceSyncStatus.PENDING,
        server_default=InferenceSyncStatus.PENDING.value,
        index=True,
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Backoff / reconcile (not part of the three-state machine; supports exponential retry).
    sync_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sync_next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
