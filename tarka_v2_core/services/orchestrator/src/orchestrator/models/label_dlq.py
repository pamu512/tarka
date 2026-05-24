"""Dead-letter queue for malformed label bus emit payloads (``tarka_label_dlq``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeEngine
from tarka_shared.database.session import Base

LABEL_DLQ_SOURCE_LABEL_PROPAGATOR = "label_propagator"


def _payload_column_type() -> TypeEngine[dict[str, Any]]:
    return JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class TarkaLabelDlqORM(Base):
    """Forensic store for label items rejected before JetStream publish."""

    __tablename__ = "tarka_label_dlq"
    __table_args__ = (
        Index("idx_tarka_label_dlq_normalized_label_id", "normalized_label_id"),
        Index("idx_tarka_label_dlq_entity_created_at", "entity_id", "created_at"),
        Index("idx_tarka_label_dlq_source_created_at", "source", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    normalized_label_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ground_truth_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_payload_column_type(), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class TarkaLabelDlqDAO:
    """Async helpers for :class:`TarkaLabelDlqORM`."""

    @classmethod
    async def record_malformed_label(
        cls,
        session: AsyncSession,
        *,
        normalized_label_id: UUID | None,
        entity_id: str | None,
        ground_truth_class: str | None,
        rejection_reason: str,
        payload: dict[str, Any],
        source: str = LABEL_DLQ_SOURCE_LABEL_PROPAGATOR,
    ) -> TarkaLabelDlqORM:
        reason = (rejection_reason or "").strip()
        if not reason:
            raise ValueError("rejection_reason is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        source_token = (source or "").strip()
        if not source_token:
            raise ValueError("source is required")

        row = TarkaLabelDlqORM(
            normalized_label_id=normalized_label_id,
            entity_id=(entity_id or "").strip() or None,
            ground_truth_class=(ground_truth_class or "").strip().upper() or None,
            rejection_reason=reason[:8192],
            payload=payload,
            source=source_token[:64],
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row
