"""Transactional outbox ORM + data access for ``tarka_outbox``."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    and_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeEngine
from tarka_shared.database.session import Base

OUTBOX_EVENT_GRAPH_INGEST = "GRAPH_INGEST"
OUTBOX_EVENT_VELOCITY_UPDATE = "VELOCITY_UPDATE"
OUTBOX_EVENT_SHADOW_TAG = "SHADOW_TAG"
OUTBOX_EVENT_SHADOW_RETRO_TAG = "SHADOW_RETRO_TAG"
OUTBOX_EVENT_LABEL_PROPAGATE = "LABEL_PROPAGATE"


class OutboxStatus(str, Enum):
    """Worker-visible outbox row states (matches ``tarka_outbox_status_check``)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OutboxTaskNotFoundError(LookupError):
    """Raised when ``task_id`` does not match an outbox row."""


def _payload_column_type() -> TypeEngine[dict[str, Any]]:
    """JSONB on PostgreSQL (migration target); JSON elsewhere (tests)."""
    return JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class OutboxORM(Base):
    """Maps to ``tarka_outbox`` (see ``migrations/20260524_001_tarka_outbox.sql``)."""

    __tablename__ = "tarka_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="tarka_outbox_status_check",
        ),
        Index("idx_tarka_outbox_idempotency_key", "idempotency_key", unique=True),
        Index("idx_tarka_outbox_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_payload_column_type(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=OutboxStatus.PENDING.value,
        server_default=OutboxStatus.PENDING.value,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxDAO:
    """Async persistence helpers for :class:`OutboxORM` (caller owns session / transaction)."""

    @staticmethod
    def _normalize_event_type(event_type: str) -> str:
        token = (event_type or "").strip()
        if not token or len(token) > 100:
            raise ValueError("event_type must be a non-empty string up to 100 characters")
        return token

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: str) -> str:
        token = (idempotency_key or "").strip()
        if not token or len(token) > 255:
            raise ValueError("idempotency_key must be a non-empty string up to 255 characters")
        return token

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        return payload

    @classmethod
    async def create_task(
        cls,
        session: AsyncSession,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> OutboxORM:
        """Insert a ``PENDING`` outbox row in the caller's open transaction."""
        row = OutboxORM(
            event_type=cls._normalize_event_type(event_type),
            idempotency_key=cls._normalize_idempotency_key(idempotency_key),
            payload=cls._normalize_payload(payload),
            status=OutboxStatus.PENDING.value,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def fetch_pending_tasks(
        cls,
        session: AsyncSession,
        batch_size: int = 100,
    ) -> list[OutboxORM]:
        """
        Claim-ready rows: ``PENDING``, or ``FAILED`` with retries remaining.

        Uses ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so concurrent pollers do not block.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        stmt = (
            select(OutboxORM)
            .where(
                or_(
                    OutboxORM.status == OutboxStatus.PENDING.value,
                    and_(
                        OutboxORM.status == OutboxStatus.FAILED.value,
                        OutboxORM.retry_count < OutboxORM.max_retries,
                    ),
                ),
            )
            .order_by(OutboxORM.created_at.asc())
            .limit(batch_size)
        )

        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        rows = (await session.scalars(stmt)).all()
        return list(rows)

    @classmethod
    async def mark_processing(cls, session: AsyncSession, task_id: UUID) -> OutboxORM:
        """Transition a claimed row to ``PROCESSING`` before side-effect execution."""
        stmt = (
            update(OutboxORM)
            .where(OutboxORM.id == task_id)
            .values(status=OutboxStatus.PROCESSING.value)
            .returning(OutboxORM)
        )
        row = (await session.scalars(stmt)).one_or_none()
        if row is None:
            raise OutboxTaskNotFoundError(f"outbox task not found: {task_id}")
        await session.flush()
        return row

    @classmethod
    async def mark_completed(cls, session: AsyncSession, task_id: UUID) -> OutboxORM:
        """Set ``status=COMPLETED`` and ``processed_at`` for ``task_id``."""
        now = datetime.now(UTC)
        stmt = (
            update(OutboxORM)
            .where(OutboxORM.id == task_id)
            .values(
                status=OutboxStatus.COMPLETED.value,
                processed_at=now,
            )
            .returning(OutboxORM)
        )
        row = (await session.scalars(stmt)).one_or_none()
        if row is None:
            raise OutboxTaskNotFoundError(f"outbox task not found: {task_id}")
        await session.flush()
        return row

    @classmethod
    async def mark_failed(
        cls,
        session: AsyncSession,
        task_id: UUID,
        error_msg: str,
    ) -> OutboxORM:
        """Increment ``retry_count``, set ``FAILED``, and record ``last_error``."""
        msg = (error_msg or "").strip()
        if not msg:
            raise ValueError("error_msg must be a non-empty string")

        stmt = (
            update(OutboxORM)
            .where(OutboxORM.id == task_id)
            .values(
                status=OutboxStatus.FAILED.value,
                retry_count=OutboxORM.retry_count + 1,
                last_error=msg[:8192],
            )
            .returning(OutboxORM)
        )
        row = (await session.scalars(stmt)).one_or_none()
        if row is None:
            raise OutboxTaskNotFoundError(f"outbox task not found: {task_id}")
        await session.flush()
        return row
