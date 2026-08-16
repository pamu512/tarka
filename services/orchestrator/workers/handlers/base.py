"""Shared outbox handler base types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graph.client import GraphClient


@dataclass(frozen=True, slots=True)
class OutboxProcessorDeps:
    session_factory: async_sessionmaker[AsyncSession]
    graph_client: GraphClient
    redis_client: Any | None
    clickhouse_client: Any | None = None
    shadow_runtime: Any | None = None
    nats_jetstream: Any | None = None
    nats_connection: Any | None = None


class BaseOutboxHandler(ABC):
    """Concrete side-effect executor for one ``tarka_outbox.event_type``."""

    event_type: ClassVar[str]

    def __init__(self, deps: OutboxProcessorDeps) -> None:
        self._deps = deps

    @abstractmethod
    async def execute(self, payload: dict[str, Any]) -> str | None:
        """Run the side effect. Return a noop reason to persist on COMPLETED, else None."""
