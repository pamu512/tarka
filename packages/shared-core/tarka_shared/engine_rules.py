"""Persisted AST rules for the v2 Python rule-engine sidecar (`engine_rules` table)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database.session import Base


class EngineRule(Base):
    """One validated :class:`rule_engine.ast_schemas.Rule` JSON blob keyed by rule ``id``."""

    __tablename__ = "engine_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
