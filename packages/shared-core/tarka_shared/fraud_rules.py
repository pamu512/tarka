"""Versioned fraud ruleset snapshots (``fraud_rules``) — append-only; one active row per deployment."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, JSON, func, text
from sqlalchemy.orm import Mapped, mapped_column

from .database.session import Base


class FraudRulesVersion(Base):
    """
    Immutable ruleset version: each deploy inserts a new row; older rows are never updated.

    The rule engine loads the single row with ``is_active`` true and the highest ``version``.
    """

    __tablename__ = "fraud_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    rules_payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        doc="JSON array of validated :class:`rule_engine.ast_schemas.Rule` objects.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
