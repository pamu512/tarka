"""Analytics plane abstraction — implementations swap via :envvar:`ENVIRONMENT` + DI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ingestor.manifest_schema import TransactionSchema


class AnalyticsProvider(ABC):
    """Contract for the orchestrator analytics tier (local DuckDB, cloud ClickHouse, tests, etc.)."""

    @abstractmethod
    def load(self) -> None:
        """Initialize backing storage (seed tables, connections, migrations)."""

    @abstractmethod
    def append_transaction(self, transaction: "TransactionSchema") -> None:
        """Append one normalized ingest envelope to the analytical store."""

    @abstractmethod
    def list_analytics_transactions(
        self,
        *,
        limit: int = 500,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, float]:
        """
        Keyset-paged rows from the unified analytical projection (newest first).

        Returns ``(rows, next_cursor, query_ms)``.
        """

    def list_analytics_transactions_legacy(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Backward-compatible helper — rows only."""
        rows, _, _ = self.list_analytics_transactions(limit=limit, cursor=None)
        return rows

    @abstractmethod
    def transactions_per_minute_by_country(self) -> list[dict[str, Any]]:
        """Minute bucket × country rollup."""

    @abstractmethod
    def transactions_per_minute_by_country_timed(self) -> tuple[list[dict[str, Any]], float]:
        """Same as :meth:`transactions_per_minute_by_country` plus server-side wall time (ms)."""

    @abstractmethod
    def velocity_sql_execute_ms(self) -> float:
        """Benchmark hook: wall time for the velocity rollup query only."""

    @abstractmethod
    def cluster_spend_velocity_for_network(
        self,
        *,
        transaction_entity_ids: Sequence[str],
        network_user_ids: Sequence[str],
        days: int = 30,
    ) -> dict[str, Any]:
        """Spend + minute velocity for a graph / user cluster."""

    @abstractmethod
    def cluster_loss_for_device_hashes(self, device_hashes: Sequence[str]) -> dict[str, Any]:
        """Session-linked loss surface for shared device fingerprints."""

    @abstractmethod
    def cluster_loss_by_device_hash(self, device_hash: str) -> dict[str, Any]:
        """Single-device convenience wrapper."""

    @abstractmethod
    def marketplace_user_stats(self, user_id: str) -> dict[str, Any]:
        """Per-user marketplace rollups (Entity Explorer)."""

    @abstractmethod
    def close(self) -> None:
        """Release connections / file handles."""
