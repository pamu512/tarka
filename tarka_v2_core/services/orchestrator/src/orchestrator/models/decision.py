"""Lekh: durable policy decision rows (trace + outcome) for orchestrator ingests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from tarka_shared.database.session import Base


class DecisionORM(Base):
    """One row per successful ``/v1/ingest`` policy evaluation when audit DB is configured."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    final_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    actions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    execution_trace_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    blocking_rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_rule_engine_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
