"""Operational signal persistence (``operational_signals`` table)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Text, TypeEngine
from tarka_shared.database.session import Base

from orchestrator.schemas.operational_signals import SignalType


class OperationalSignalNotFoundError(LookupError):
    """Raised when an operational signal row cannot be resolved."""


def _metadata_column_type() -> TypeEngine[dict[str, Any]]:
    return JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class OperationalSignalORM(Base):
    """Maps to ``operational_signals`` (see ``migrations/20260525_001_operational_signals.sql``)."""

    __tablename__ = "operational_signals"
    __table_args__ = (
        Index("idx_operational_signals_idempotency_key", "idempotency_key", unique=True),
        Index("idx_operational_signals_target_entity_created_at", "target_entity_id", "created_at"),
        Index("idx_operational_signals_signal_type_created_at", "signal_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        _metadata_column_type(),
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class OperationalSignalDAO:
    """Async helpers for :class:`OperationalSignalORM` (caller owns session / transaction)."""

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: str) -> str:
        token = (idempotency_key or "").strip()
        if not token or len(token) > 255:
            raise ValueError("idempotency_key must be a non-empty string up to 255 characters")
        return token

    @staticmethod
    def _normalize_target_entity_id(target_entity_id: UUID | str) -> str:
        if isinstance(target_entity_id, UUID):
            token = str(target_entity_id)
        else:
            token = str(target_entity_id or "").strip()
        if not token or len(token) > 512:
            raise ValueError("target_entity_id must be a non-empty string up to 512 characters")
        return token

    @staticmethod
    def _normalize_signal_type(signal_type: SignalType | str) -> str:
        if isinstance(signal_type, SignalType):
            token = signal_type.value
        else:
            token = str(signal_type or "").strip()
        if not token or len(token) > 100:
            raise ValueError("signal_type must be a non-empty string up to 100 characters")
        return token

    @staticmethod
    def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            raise TypeError("metadata must be a dict")
        return metadata

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        idempotency_key: str,
        target_entity_id: UUID | str,
        signal_type: SignalType | str,
        metadata: dict[str, Any],
    ) -> OperationalSignalORM:
        """Insert an operational signal row in the caller's open transaction."""
        row = OperationalSignalORM(
            idempotency_key=cls._normalize_idempotency_key(idempotency_key),
            target_entity_id=cls._normalize_target_entity_id(target_entity_id),
            signal_type=cls._normalize_signal_type(signal_type),
            metadata_json=cls._normalize_metadata(metadata),
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def fetch_by_idempotency_key(
        cls,
        session: AsyncSession,
        idempotency_key: str,
    ) -> OperationalSignalORM | None:
        token = cls._normalize_idempotency_key(idempotency_key)
        stmt = select(OperationalSignalORM).where(OperationalSignalORM.idempotency_key == token)
        return (await session.scalars(stmt)).one_or_none()
