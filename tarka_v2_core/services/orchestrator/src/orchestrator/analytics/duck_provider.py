"""
**Local** analytics plane: DuckDB (in-memory or ``*.duckdb`` file).

This is the default implementation of :class:`~orchestrator.analytics.provider.AnalyticsProvider`
when ``ENVIRONMENT`` is not a cloud profile (see :mod:`orchestrator.analytics.factory`).

Seed data: ``data/seed_data.parquet`` (next to this module) or :envvar:`ORCHESTRATOR_DUCK_SEED_PARQUET`.
Optional persistent catalog: :envvar:`ORCHESTRATOR_LOCAL_ANALYTICS_DUCKDB` (path to a ``.duckdb`` file).

Ingestion appends normalized rows into ``ingested_raw``; :obj:`v_analytics_transactions` unions seed
``txns`` with those rows.

**Cluster loss** (Prompt 123): session union across device fingerprints in ``metadata``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
from ingestor.manifest_schema import TransactionSchema

from orchestrator.analytics.provider import AnalyticsProvider

logger = logging.getLogger(__name__)

_DEFAULT_RELATIVE = Path(__file__).resolve().parent / "data" / "seed_data.parquet"

_VELOCITY_SQL = """
SELECT
  date_trunc('minute', ts) AS minute_bucket,
  country,
  COUNT(*)::BIGINT AS txn_count
FROM v_analytics_transactions
GROUP BY 1, 2
ORDER BY 1 ASC, 3 DESC, 2 ASC
"""

_ENTITY_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class LocalAnalytics(AnalyticsProvider):
    """Thread-safe DuckDB implementation of the analytics plane (demo / local / CI)."""

    def __init__(
        self,
        *,
        parquet_path: Path | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        raw = parquet_path or os.environ.get("ORCHESTRATOR_DUCK_SEED_PARQUET", "").strip()
        self._parquet_path = Path(raw) if raw else _DEFAULT_RELATIVE
        if database_path is not None:
            db_str = str(Path(database_path).expanduser()).strip()
        else:
            db_str = (os.environ.get("ORCHESTRATOR_LOCAL_ANALYTICS_DUCKDB") or "").strip()
        if db_str:
            Path(db_str).parent.mkdir(parents=True, exist_ok=True)
            self._con = duckdb.connect(database=db_str)
        else:
            self._con = duckdb.connect(database=":memory:")
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> LocalAnalytics:
        """Build + ``load()`` using env seed / DuckDB path (used by :func:`~orchestrator.analytics.factory.build_analytics_provider`)."""
        inst = cls()
        inst.load()
        return inst

    def _ensure_stream_artifacts(self) -> None:
        """Append buffer + unified view (must run after ``txns`` exists)."""
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS ingested_raw (
                ts TIMESTAMP,
                country VARCHAR,
                amount DOUBLE,
                entity_id VARCHAR,
                metadata VARCHAR
            )
            """,
        )
        self._con.execute(
            """
            CREATE OR REPLACE VIEW v_analytics_transactions AS
            SELECT ts, country, amount, entity_id, CAST(NULL AS VARCHAR) AS metadata FROM txns
            UNION ALL
            SELECT ts, country, amount, entity_id, metadata FROM ingested_raw
            """,
        )

    def load(self) -> None:
        """Load seed Parquet into table ``txns`` (columns: ``ts``, ``country``, ``amount``, ``entity_id``)."""
        with self._lock:
            try:
                has_txns = int(
                    self._con.execute(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = 'main' AND table_name = 'txns'",
                    ).fetchone()[0]
                )
            except Exception:
                has_txns = 0
        if has_txns:
            with self._lock:
                self._ensure_stream_artifacts()
            logger.info("orchestrator_local_analytics_reuse_existing_txns")
            return

        p = self._parquet_path
        if p.is_file():
            q = f"CREATE TABLE txns AS SELECT * FROM read_parquet('{p.as_posix()}')"
            with self._lock:
                self._con.execute(q)
                n = int(self._con.execute("SELECT COUNT(*) FROM txns").fetchone()[0])
                self._ensure_stream_artifacts()
            logger.info(
                "orchestrator_local_analytics_loaded path=%s rows=%s",
                p,
                n,
            )
            return

        logger.warning(
            "orchestrator_local_analytics_seed_missing path=%s building_synthetic_fallback",
            p,
        )
        with self._lock:
            self._con.execute(
                """
                CREATE TABLE txns AS
                SELECT
                    (TIMESTAMP '2026-01-01 00:00:00' + (i * INTERVAL 1 SECOND)) AS ts,
                    (['US', 'CA', 'GB', 'DE', 'FR'])[1 + (i % 5)] AS country,
                    (10 + (i % 97))::DOUBLE AS amount,
                    uuid() AS entity_id
                FROM range(5000) AS t(i)
                """,
            )
            self._ensure_stream_artifacts()

    def cluster_spend_velocity_for_network(
        self,
        *,
        transaction_entity_ids: Sequence[str],
        network_user_ids: Sequence[str],
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Aggregate spend over ``days`` for rows in ``v_analytics_transactions`` tied to the cluster.

        Matches ``entity_id`` (UUID strings) **or** ``metadata.user_id`` in the JSON ``metadata`` column.
        Emits ``spend_last_2h``, ``spike_pct_vs_flat_baseline_2h`` (percent uplift vs flat 2h slice of the
        remainder of the window), and minute-level velocity rows for the last 48h (for dashboards).
        """
        d = max(1, min(int(days), 366))
        clean_tx = [x.strip() for x in transaction_entity_ids if _ENTITY_UUID_RE.match((x or "").strip())]
        clean_u = [
            x.strip()
            for x in network_user_ids
            if x and len(x.strip()) <= 512 and "\x00" not in x and "'" not in x and '"' not in x
        ]
        empty: dict[str, Any] = {
            "window_days": d,
            "cluster_transaction_ids_used": clean_tx,
            "cluster_user_ids_used": clean_u,
            "total_spend_window": 0.0,
            "txn_count_window": 0,
            "spend_last_2h": 0.0,
            "spend_excluding_last_2h": 0.0,
            "spike_pct_vs_flat_baseline_2h": None,
            "minute_velocity_last_48h": [],
        }
        if not clean_tx and not clean_u:
            return empty

        ors: list[str] = []
        bind_in: list[Any] = []
        if clean_tx:
            ors.append(f"entity_id IN ({','.join(['?'] * len(clean_tx))})")
            bind_in.extend(clean_tx)
        if clean_u:
            ors.append(
                "("
                "try_cast(metadata AS JSON) IS NOT NULL AND "
                f"json_extract_string(try_cast(metadata AS JSON), '$.user_id') IN ({','.join(['?'] * len(clean_u))})"
                ")"
            )
            bind_in.extend(clean_u)
        where_net = "(" + " OR ".join(ors) + ")"
        agg_sql = f"""
        SELECT
          COALESCE(SUM(amount), 0)::DOUBLE AS total_spend_window,
          COUNT(*)::BIGINT AS txn_count_window,
          COALESCE(SUM(CASE WHEN ts >= CURRENT_TIMESTAMP - INTERVAL 2 HOUR THEN amount ELSE 0 END), 0)::DOUBLE AS spend_last_2h,
          COALESCE(SUM(CASE WHEN ts < CURRENT_TIMESTAMP - INTERVAL 2 HOUR THEN amount ELSE 0 END), 0)::DOUBLE AS spend_excl_2h
        FROM v_analytics_transactions
        WHERE ts >= CURRENT_TIMESTAMP - (?::INTEGER) * INTERVAL '1 day'
          AND {where_net}
        """
        agg_bind = [d] + bind_in
        vel_sql = f"""
        SELECT date_trunc('minute', ts) AS minute_bucket, COALESCE(SUM(amount), 0)::DOUBLE AS spend
        FROM v_analytics_transactions
        WHERE ts >= CURRENT_TIMESTAMP - INTERVAL 48 HOUR AND {where_net}
        GROUP BY 1 ORDER BY 1 ASC
        """
        with self._lock:
            row = self._con.execute(agg_sql, agg_bind).fetchone()
            cur = self._con.execute(vel_sql, bind_in)
            colnames = [x[0] for x in (cur.description or ())]
            vel_rows: list[dict[str, Any]] = []
            for tup in cur.fetchall():
                rowd = dict(zip(colnames, tup))
                mb = rowd.get("minute_bucket")
                if hasattr(mb, "isoformat"):
                    rowd["minute_bucket"] = mb.isoformat()
                vel_rows.append(rowd)

        tot, n_tx, s2h, srest = row
        total = float(tot or 0)
        spend_2h = float(s2h or 0)
        spend_rest = float(srest or 0)
        slots = max(d * 12 - 1, 1)
        baseline_2h = spend_rest / float(slots) if slots else 0.0
        spike_pct: float | None = None
        if baseline_2h > 1e-9:
            spike_pct = (spend_2h / baseline_2h - 1.0) * 100.0

        return {
            **empty,
            "total_spend_window": total,
            "txn_count_window": int(n_tx or 0),
            "spend_last_2h": spend_2h,
            "spend_excluding_last_2h": spend_rest,
            "spike_pct_vs_flat_baseline_2h": spike_pct,
            "minute_velocity_last_48h": vel_rows,
        }

    def append_transaction(self, transaction: TransactionSchema) -> None:
        """Append one raw envelope row to ``ingested_raw`` (idempotent replay may duplicate)."""
        meta = transaction.metadata or {}
        if transaction.country and str(transaction.country).strip():
            country = str(transaction.country).strip()
        else:
            raw_c = meta.get("country")
            country = str(raw_c).strip() if isinstance(raw_c, str) and raw_c.strip() else "ZZ"
        entity_id = str(transaction.entity_id)
        ts = transaction.timestamp
        amount = float(transaction.amount)
        meta_s = json.dumps(meta, separators=(",", ":"), default=str)
        with self._lock:
            self._con.execute(
                "INSERT INTO ingested_raw VALUES (?, ?, ?, ?, ?)",
                [ts, country, amount, entity_id, meta_s],
            )

    def list_analytics_transactions(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent rows from ``v_analytics_transactions`` (newest ``ts`` first)."""
        lim = max(1, min(int(limit), 10_000))
        q = f"SELECT * FROM v_analytics_transactions ORDER BY ts DESC LIMIT {lim}"
        with self._lock:
            cur = self._con.execute(q)
            colnames = [d[0] for d in (cur.description or ())]
            tuples = cur.fetchall()
        rows: list[dict[str, Any]] = []
        for tup in tuples:
            out = dict(zip(colnames, tup))
            for k, v in list(out.items()):
                if hasattr(v, "isoformat"):
                    out[k] = v.isoformat()
            rows.append(out)
        return rows

    def transactions_per_minute_by_country(self) -> list[dict[str, Any]]:
        """Return rows: ``minute_bucket`` (ISO), ``country``, ``txn_count``."""
        with self._lock:
            cur = self._con.execute(_VELOCITY_SQL)
            colnames = [d[0] for d in (cur.description or ())]
            tuples = cur.fetchall()
        rows: list[dict[str, Any]] = []
        for tup in tuples:
            out = dict(zip(colnames, tup))
            mb = out.get("minute_bucket")
            if hasattr(mb, "isoformat"):
                out["minute_bucket"] = mb.isoformat()
            rows.append(out)
        return rows

    def transactions_per_minute_by_country_timed(self) -> tuple[list[dict[str, Any]], float]:
        """Same as :meth:`transactions_per_minute_by_country` plus wall time in milliseconds."""
        t0 = time.perf_counter()
        data = self.transactions_per_minute_by_country()
        ms = (time.perf_counter() - t0) * 1000.0
        return data, ms

    def velocity_sql_execute_ms(self) -> float:
        """Wall time for DuckDB ``execute`` + ``fetchall`` only (no Python row dicts). For benchmarks."""
        with self._lock:
            t0 = time.perf_counter()
            cur = self._con.execute(_VELOCITY_SQL)
            cur.fetchall()
            return (time.perf_counter() - t0) * 1000.0

    def cluster_loss_for_device_hashes(self, device_hashes: Sequence[str]) -> dict[str, Any]:
        """
        **Cluster loss**: sum of ``amount`` for all rows whose session id belongs to the union of
        session keys ever seen together with any of the given device fingerprints in ``metadata``.

        Device fingerprint is resolved from JSON keys ``device_hash``, ``device_id``,
        ``device_fingerprint``, or ``graph_device_id`` (first non-empty), case-insensitive match.
        Session key is ``session_id``, ``linked_session_id``, or ``device_session_id`` (first
        non-empty). Intended for dispute / fraud ops dashboards as *total risk across accounts*
        tied to a shared device surface.
        """
        clean: list[str] = []
        for raw in device_hashes:
            s = (raw or "").strip()
            if not s or len(s) > 512 or "\x00" in s or "'" in s or '"' in s:
                continue
            if s not in clean:
                clean.append(s)
        empty: dict[str, Any] = {
            "cluster_loss": 0.0,
            "linked_txn_count": 0,
            "distinct_session_count": 0,
            "device_hashes_used": clean,
        }
        if not clean:
            return empty

        in_dev = ",".join(["?"] * len(clean))
        sql = f"""
        WITH base AS (
          SELECT
            amount,
            lower(trim(coalesce(
              json_extract_string(try_cast(metadata AS JSON), '$.device_hash'),
              json_extract_string(try_cast(metadata AS JSON), '$.device_id'),
              json_extract_string(try_cast(metadata AS JSON), '$.device_fingerprint'),
              json_extract_string(try_cast(metadata AS JSON), '$.graph_device_id'),
              ''
            ))) AS dev_norm,
            nullif(trim(coalesce(
              json_extract_string(try_cast(metadata AS JSON), '$.session_id'),
              json_extract_string(try_cast(metadata AS JSON), '$.linked_session_id'),
              json_extract_string(try_cast(metadata AS JSON), '$.device_session_id'),
              ''
            )), '') AS session_key
          FROM v_analytics_transactions
          WHERE metadata IS NOT NULL AND length(trim(metadata)) > 0
        ),
        sessions_from_devices AS (
          SELECT DISTINCT session_key
          FROM base
          WHERE dev_norm IN ({in_dev})
            AND session_key IS NOT NULL
        )
        SELECT
          coalesce(sum(b.amount), 0)::DOUBLE AS cluster_loss,
          count(*)::BIGINT AS linked_txn_count,
          count(distinct b.session_key)::BIGINT AS distinct_session_count
        FROM base AS b
        WHERE b.session_key IN (SELECT session_key FROM sessions_from_devices)
        """
        with self._lock:
            row = self._con.execute(sql, clean).fetchone()
        if not row:
            return empty
        loss, n_tx, n_sess = row
        return {
            **empty,
            "cluster_loss": float(loss or 0),
            "linked_txn_count": int(n_tx or 0),
            "distinct_session_count": int(n_sess or 0),
        }

    def cluster_loss_by_device_hash(self, device_hash: str) -> dict[str, Any]:
        """Single-device convenience wrapper for :meth:`cluster_loss_for_device_hashes`."""
        return self.cluster_loss_for_device_hashes([device_hash])

    def marketplace_user_stats(self, user_id: str) -> dict[str, Any]:
        """
        Marketplace operator metrics for **Entity Explorer**: spend, distinct listings, promo success.

        Reads ``metadata`` JSON on ``v_analytics_transactions`` rows where ``$.user_id`` matches.
        ``promo_success_rate`` is the mean of 1.0/0.0 rows where ``$.promo_applied`` is truthy and
        ``$.promo_outcome`` resolves to success/failure; ``None`` when no qualifying promo rows.
        """
        uid = (user_id or "").strip()
        base: dict[str, Any] = {
            "source": "duckdb",
            "user_id": uid,
            "total_spend": 0.0,
            "txn_count": 0,
            "listing_count": 0,
            "promo_success_rate": None,
            "promo_denominator": 0,
        }
        if not uid or len(uid) > 512 or "\x00" in uid or "'" in uid or '"' in uid:
            return base
        sql = """
        SELECT
          COALESCE(SUM(amount), 0)::DOUBLE AS total_spend,
          COUNT(*)::BIGINT AS txn_count,
          COUNT(DISTINCT listing_id) FILTER (
            WHERE listing_id IS NOT NULL AND LENGTH(TRIM(listing_id)) > 0
          )::BIGINT AS listing_count,
          AVG(promo_score) FILTER (WHERE promo_score IS NOT NULL) AS promo_success_rate,
          COUNT(promo_score) FILTER (WHERE promo_score IS NOT NULL)::BIGINT AS promo_denominator
        FROM (
          SELECT
            amount,
            NULLIF(TRIM(json_extract_string(try_cast(metadata AS JSON), '$.listing_id')), '') AS listing_id,
            CASE
              WHEN lower(COALESCE(json_extract_string(try_cast(metadata AS JSON), '$.promo_applied'), ''))
                IN ('true', '1', 'yes')
                THEN CASE
                  WHEN lower(COALESCE(
                    json_extract_string(try_cast(metadata AS JSON), '$.promo_outcome'), ''
                  )) IN ('success', 'won', 'approved')
                    THEN 1.0
                  WHEN lower(COALESCE(
                    json_extract_string(try_cast(metadata AS JSON), '$.promo_outcome'), ''
                  )) IN ('failure', 'lost', 'denied')
                    THEN 0.0
                  ELSE NULL
                END
              ELSE NULL
            END AS promo_score
          FROM v_analytics_transactions
          WHERE json_extract_string(try_cast(metadata AS JSON), '$.user_id') = ?
        ) q
        """
        with self._lock:
            row = self._con.execute(sql, [uid]).fetchone()
        if not row:
            return base
        tot, n_tx, n_list, promo_avg, promo_n = row
        pr: float | None = None
        if promo_avg is not None:
            try:
                pr = float(promo_avg)
            except (TypeError, ValueError):
                pr = None
        return {
            **base,
            "total_spend": float(tot or 0),
            "txn_count": int(n_tx or 0),
            "listing_count": int(n_list or 0),
            "promo_success_rate": pr,
            "promo_denominator": int(promo_n or 0),
        }

    def close(self) -> None:
        with self._lock:
            self._con.close()


# Backward-compatible name used across tests and older call sites.
DuckAnalyticsProvider = LocalAnalytics
