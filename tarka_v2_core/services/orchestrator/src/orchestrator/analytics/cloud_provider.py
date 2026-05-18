"""Distributed ClickHouse backend for :class:`~orchestrator.analytics.provider.AnalyticsProvider`."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from ingestor.manifest_schema import TransactionSchema

from orchestrator.analytics.provider import AnalyticsProvider
from orchestrator.analytics.transaction_cursor import decode_transaction_cursor, encode_transaction_cursor

logger = logging.getLogger(__name__)

_EMPTY_CLUSTER_VELOCITY: dict[str, Any] = {
    "window_days": 30,
    "cluster_transaction_ids_used": [],
    "cluster_user_ids_used": [],
    "total_spend_window": 0.0,
    "txn_count_window": 0,
    "spend_last_2h": 0.0,
    "spend_excluding_last_2h": 0.0,
    "spike_pct_vs_flat_baseline_2h": None,
    "minute_velocity_last_48h": [],
}

_EMPTY_CLUSTER_LOSS: dict[str, Any] = {
    "cluster_loss": 0.0,
    "linked_txn_count": 0,
    "distinct_session_count": 0,
    "device_hashes_used": [],
}


class CloudAnalytics(AnalyticsProvider):
    """
    ClickHouse-backed analytics (production / staging ``ENVIRONMENT``).

    Uses ``clickhouse-connect`` when installed and ``CLICKHOUSE_HOST`` (or ``CLICKHOUSE_URL``) is set.
    Until read-path SQL is fully aligned with DuckDB views, query endpoints return empty-safe shapes;
    ``append_transaction`` inserts into ``orchestrator_analytics_ingested`` when the client is active.
    """

    _TABLE = "orchestrator_analytics_ingested"

    def __init__(self, *, client: Any | None) -> None:
        self._client = client
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> CloudAnalytics:
        client = _try_connect_clickhouse()
        inst = cls(client=client)
        inst.load()
        return inst

    def load(self) -> None:
        if self._client is None:
            logger.warning(
                "orchestrator_cloud_analytics_no_client "
                "(install tarka-orchestrator[cloud] and set CLICKHOUSE_HOST / credentials)",
            )
            return
        self._client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self._TABLE} (
                ts DateTime64(3),
                country String,
                amount Float64,
                entity_id String,
                metadata String
            )
            ENGINE = MergeTree
            ORDER BY (ts, entity_id)
            """,
        )
        logger.info("orchestrator_cloud_analytics_ready table=%s", self._TABLE)

    def append_transaction(self, transaction: TransactionSchema) -> None:
        if self._client is None:
            logger.debug("orchestrator_cloud_analytics_append_skipped_no_client")
            return
        meta = transaction.metadata or {}
        if transaction.country and str(transaction.country).strip():
            country = str(transaction.country).strip()
        else:
            raw_c = meta.get("country")
            country = str(raw_c).strip() if isinstance(raw_c, str) and raw_c.strip() else "ZZ"
        entity_id = str(transaction.entity_id)
        ts = transaction.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        amount = float(transaction.amount)
        meta_s = json.dumps(meta, separators=(",", ":"), default=str)
        row = [[ts.replace(tzinfo=None), country, amount, entity_id, meta_s]]
        with self._lock:
            self._client.insert(
                self._TABLE,
                row,
                column_names=["ts", "country", "amount", "entity_id", "metadata"],
            )

    def list_analytics_transactions(
        self,
        *,
        limit: int = 500,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, float]:
        if self._client is None:
            return [], None, 0.0
        lim = max(1, min(int(limit), 10_000))
        decoded = decode_transaction_cursor(cursor)
        t0 = time.perf_counter()
        if decoded is None:
            q = f"""
            SELECT ts, country, amount, entity_id, metadata
            FROM {self._TABLE}
            ORDER BY ts DESC, entity_id DESC, amount DESC
            LIMIT {lim}
            """
            params: list[Any] = []
        else:
            ts_c, eid_c, amt_c = decoded
            q = f"""
            SELECT ts, country, amount, entity_id, metadata
            FROM {self._TABLE}
            WHERE (ts < toDateTime64(%(ts)s, 3))
               OR (ts = toDateTime64(%(ts)s, 3) AND entity_id < %(eid)s)
               OR (ts = toDateTime64(%(ts)s, 3) AND entity_id = %(eid)s AND amount < %(amt)s)
            ORDER BY ts DESC, entity_id DESC, amount DESC
            LIMIT {lim}
            """
            params = {"ts": ts_c, "eid": eid_c, "amt": amt_c}
        with self._lock:
            result = self._client.query(q, parameters=params) if params else self._client.query(q)
        ms = (time.perf_counter() - t0) * 1000.0
        rows: list[dict[str, Any]] = []
        for tup in result.result_rows:
            ts, country, amount, entity_id, metadata = tup
            rows.append(
                {
                    "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "country": country,
                    "amount": amount,
                    "entity_id": entity_id,
                    "metadata": metadata,
                },
            )
        next_cursor: str | None = None
        if len(rows) >= lim:
            last = rows[-1]
            ts_s = str(last.get("ts") or "")
            eid_s = str(last.get("entity_id") or "")
            amt_v = last.get("amount")
            if ts_s and eid_s and isinstance(amt_v, (int, float)):
                next_cursor = encode_transaction_cursor(ts=ts_s, entity_id=eid_s, amount=float(amt_v))
        return rows, next_cursor, ms

    def transactions_per_minute_by_country(self) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        q = f"""
        SELECT
          toStartOfMinute(ts) AS minute_bucket,
          country,
          count()::UInt64 AS txn_count
        FROM {self._TABLE}
        GROUP BY 1, 2
        ORDER BY minute_bucket ASC, txn_count DESC, country ASC
        """
        with self._lock:
            result = self._client.query(q)
        out: list[dict[str, Any]] = []
        for tup in result.result_rows:
            mb, country, txn_count = tup
            out.append(
                {
                    "minute_bucket": mb.isoformat() if hasattr(mb, "isoformat") else str(mb),
                    "country": country,
                    "txn_count": int(txn_count),
                },
            )
        return out

    def transactions_per_minute_by_country_timed(self) -> tuple[list[dict[str, Any]], float]:
        t0 = time.perf_counter()
        data = self.transactions_per_minute_by_country()
        return data, (time.perf_counter() - t0) * 1000.0

    def velocity_sql_execute_ms(self) -> float:
        t0 = time.perf_counter()
        _ = self.transactions_per_minute_by_country()
        return (time.perf_counter() - t0) * 1000.0

    def cluster_spend_velocity_for_network(
        self,
        *,
        transaction_entity_ids: Sequence[str],
        network_user_ids: Sequence[str],
        days: int = 30,
    ) -> dict[str, Any]:
        _ = (transaction_entity_ids, network_user_ids, days)
        return {**_EMPTY_CLUSTER_VELOCITY, "window_days": max(1, min(int(days), 366))}

    def cluster_loss_for_device_hashes(self, device_hashes: Sequence[str]) -> dict[str, Any]:
        clean: list[str] = []
        for raw in device_hashes:
            s = (raw or "").strip()
            if s and len(s) <= 512 and "\x00" not in s and "'" not in s and '"' not in s and s not in clean:
                clean.append(s)
        return {**_EMPTY_CLUSTER_LOSS, "device_hashes_used": clean}

    def cluster_loss_by_device_hash(self, device_hash: str) -> dict[str, Any]:
        return self.cluster_loss_for_device_hashes([device_hash])

    def marketplace_user_stats(self, user_id: str) -> dict[str, Any]:
        uid = (user_id or "").strip()
        return {
            "source": "clickhouse",
            "available": self._client is not None,
            "user_id": uid,
            "total_spend": 0.0,
            "txn_count": 0,
            "listing_count": 0,
            "promo_success_rate": None,
            "promo_denominator": 0,
        }

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.exception("orchestrator_cloud_analytics_close_failed")


def _try_connect_clickhouse() -> Any | None:
    host = (os.environ.get("CLICKHOUSE_HOST") or "").strip()
    url = (os.environ.get("CLICKHOUSE_URL") or "").strip()
    if not host and not url:
        return None
    try:
        import clickhouse_connect  # noqa: PLC0415 — optional ``tarka-orchestrator[cloud]``
    except ImportError:
        logger.warning("orchestrator_cloud_analytics_clickhouse_connect_missing")
        return None
    user = (os.environ.get("CLICKHOUSE_USER") or "default").strip()
    password = (os.environ.get("CLICKHOUSE_PASSWORD") or "").strip()
    database = (os.environ.get("CLICKHOUSE_DATABASE") or "default").strip()
    try:
        if url:
            return clickhouse_connect.get_client(dsn=url)
        port = int((os.environ.get("CLICKHOUSE_PORT") or "8443").strip() or "8443")
        secure = (os.environ.get("CLICKHOUSE_SECURE") or "true").strip().lower() in ("1", "true", "yes")
        return clickhouse_connect.get_client(
            host=host,
            port=port,
            username=user,
            password=password,
            database=database,
            secure=secure,
        )
    except Exception:
        logger.exception("orchestrator_cloud_analytics_connect_failed")
        return None
