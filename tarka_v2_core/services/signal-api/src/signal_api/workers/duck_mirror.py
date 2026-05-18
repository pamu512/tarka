"""
DuckDB **mirror** worker: JetStream ``signals.raw`` → ``transactions.duckdb`` table ``raw_signals``.

Batches messages and flushes at most every ``SIGNAL_DUCK_MIRROR_FLUSH_SEC`` (default **5** s) in a
single **transaction** to reduce checkpoint / disk churn vs per-message inserts (keeps the local
mirror bursty relative to continuous remote writes).

**TTL (Prompt 117)** — rows older than ``SIGNAL_DUCK_RAW_SIGNALS_TTL_DAYS`` (default **30**) on
``raw_signals.ingested_at`` are deleted on a wall-clock interval ``SIGNAL_DUCK_MIRROR_TTL_INTERVAL_SEC``
(default **86400**, once per day). SQL uses ``ingested_at`` as the mirror ingest timestamp (logical
equivalent of a ``timestamp`` retention column).

Run::

    NATS_URL=nats://127.0.0.1:4222 python -m signal_api.workers.duck_mirror
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

import duckdb

from signal_api.durable_handover import ensure_signals_jetstream_stream
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema

logger = logging.getLogger(__name__)

_DEFAULT_DUCK_PATH = "transactions.duckdb"
_DEFAULT_FLUSH_SEC = 5.0
_DEFAULT_SUBJECT = "signals.raw"
_DEFAULT_STREAM = "SIGNALS"
_DEFAULT_TTL_DAYS = 30
_DEFAULT_TTL_INTERVAL_SEC = 86_400.0


def raw_signals_ddl() -> str:
    return """
    CREATE TABLE IF NOT EXISTS raw_signals (
        ingested_at TIMESTAMPTZ NOT NULL,
        session_id VARCHAR NOT NULL,
        signal_json VARCHAR NOT NULL,
        nats_stream_seq BIGINT
    );
    """


def ensure_raw_signals_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(raw_signals_ddl())


def purge_expired_raw_signals(con: duckdb.DuckDBPyConnection, *, ttl_days: int) -> int:
    """
    Delete ``raw_signals`` rows whose ``ingested_at`` is older than ``ttl_days`` (UTC wall clock).

    Returns the number of rows removed (via ``RETURNING``). Issues ``CHECKPOINT`` so on-disk
    ``*.duckdb`` size can stabilize after large deletes.
    """
    if ttl_days < 1:
        raise ValueError("ttl_days must be >= 1")
    ensure_raw_signals_table(con)
    res = con.execute(
        f"""
        DELETE FROM raw_signals
        WHERE ingested_at < (now() - INTERVAL '{int(ttl_days)} days')
        RETURNING 1
        """,
    )
    deleted = len(res.fetchall())
    try:
        con.execute("CHECKPOINT")
    except Exception:
        logger.debug("duck_mirror_ttl_checkpoint_skipped", exc_info=True)
    return deleted


def rows_from_validated(
    items: list[tuple[Any, UnifiedSignalSchema]],
) -> list[tuple[Any, ...]]:
    """Build ``raw_signals`` rows (``ingested_at`` is flush time, UTC)."""
    now = datetime.now(UTC)
    out: list[tuple[Any, ...]] = []
    for msg, body in items:
        seq: int | None = None
        try:
            md = getattr(msg, "metadata", None)
            if md is not None:
                seq_obj = getattr(md, "sequence", None)
                if seq_obj is not None and getattr(seq_obj, "stream", None) is not None:
                    seq = int(seq_obj.stream)
        except Exception:
            seq = None
        out.append(
            (
                now,
                str(body.session_id),
                json.dumps(
                    body.model_dump(mode="json", by_alias=True),
                    separators=(",", ":"),
                    default=str,
                ),
                seq,
            ),
        )
    return out


def flush_batch_to_duckdb(con: duckdb.DuckDBPyConnection, rows: list[tuple[Any, ...]]) -> int:
    """
    One **BEGIN** … **executemany** … **COMMIT** per batch so DuckDB amortizes storage updates
    (fewer small writes than one transaction per NATS message).
    """
    if not rows:
        return 0
    con.execute("BEGIN TRANSACTION")
    try:
        con.executemany(
            "INSERT INTO raw_signals (ingested_at, session_id, signal_json, nats_stream_seq) VALUES (?, ?, ?, ?)",
            rows,
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


async def _ack_all(msgs: list[Any]) -> None:
    for m in msgs:
        await m.ack()


async def _nak_all(msgs: list[Any]) -> None:
    for m in msgs:
        try:
            await m.nak()
        except Exception:
            logger.exception("duck_mirror_nak_failed")


async def run_mirror_worker(*, stop: asyncio.Event | None = None) -> None:
    duck_path = (os.environ.get("SIGNAL_DUCKDB_PATH") or _DEFAULT_DUCK_PATH).strip()
    flush_sec = max(0.25, float(os.environ.get("SIGNAL_DUCK_MIRROR_FLUSH_SEC", str(_DEFAULT_FLUSH_SEC))))
    nats_url = (os.environ.get("SIGNAL_NATS_URL") or os.environ.get("NATS_URL") or "").strip()
    subject = (os.environ.get("SIGNAL_NATS_SIGNALS_SUBJECT") or _DEFAULT_SUBJECT).strip()
    stream_name = (os.environ.get("SIGNAL_NATS_STREAM") or _DEFAULT_STREAM).strip()
    durable = (os.environ.get("SIGNAL_DUCK_MIRROR_DURABLE") or "duck-mirror").strip()
    max_batch = max(100, min(int(os.environ.get("SIGNAL_DUCK_MIRROR_MAX_BATCH", "10000")), 500_000))
    ttl_days = max(1, int(os.environ.get("SIGNAL_DUCK_RAW_SIGNALS_TTL_DAYS", str(_DEFAULT_TTL_DAYS))))
    ttl_interval = max(60.0, float(os.environ.get("SIGNAL_DUCK_MIRROR_TTL_INTERVAL_SEC", str(_DEFAULT_TTL_INTERVAL_SEC))))

    if not nats_url:
        raise RuntimeError("Set SIGNAL_NATS_URL or NATS_URL for the Duck mirror worker")

    import nats
    from nats.errors import TimeoutError as NatsTimeoutError

    def _open_duck() -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(duck_path)
        ensure_raw_signals_table(con)
        return con

    con = await asyncio.to_thread(_open_duck)
    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    await ensure_signals_jetstream_stream(js)
    psub = await js.pull_subscribe(subject, durable=durable, stream=stream_name)

    stop_ev = stop or asyncio.Event()

    def _stop() -> None:
        stop_ev.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    pending: list[tuple[Any, UnifiedSignalSchema]] = []
    last_flush = time.monotonic()
    last_ttl = time.monotonic()

    try:
        while not stop_ev.is_set():
            if time.monotonic() - last_ttl >= ttl_interval:
                try:

                    def _ttl() -> int:
                        return purge_expired_raw_signals(con, ttl_days=ttl_days)

                    removed = await asyncio.to_thread(_ttl)
                    logger.info("duck_mirror_ttl_purge ttl_days=%s removed_rows=%s", ttl_days, removed)
                except Exception:
                    logger.exception("duck_mirror_ttl_purge_failed")
                last_ttl = time.monotonic()

            wait_budget = max(0.05, flush_sec - (time.monotonic() - last_flush))
            try:
                msgs = await psub.fetch(batch=512, timeout=wait_budget)
            except NatsTimeoutError:
                msgs = []

            for m in msgs:
                try:
                    body = UnifiedSignalSchema.model_validate_json(m.data)
                    pending.append((m, body))
                except Exception:
                    logger.exception("duck_mirror_bad_payload_terminated")
                    await m.term()

            should_flush = bool(pending) and (
                time.monotonic() - last_flush >= flush_sec or len(pending) >= max_batch
            )
            if should_flush:
                batch = pending
                pending = []
                rows = rows_from_validated(batch)
                msgs_only = [pair[0] for pair in batch]
                try:
                    await asyncio.to_thread(flush_batch_to_duckdb, con, rows)
                    await _ack_all(msgs_only)
                    logger.info("duck_mirror_flush rows=%s", len(rows))
                except Exception:
                    logger.exception("duck_mirror_flush_failed_nak")
                    await _nak_all(msgs_only)
                finally:
                    last_flush = time.monotonic()
    finally:
        await psub.unsubscribe()
        await nc.drain()
        await nc.close()

        def _close() -> None:
            con.close()

        await asyncio.to_thread(_close)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Mirror signals.raw JetStream into DuckDB raw_signals.")
    parser.parse_args(argv)
    try:
        asyncio.run(run_mirror_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
