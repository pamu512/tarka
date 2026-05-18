"""Pluggable async messaging (NATS production, in-process broker for Tarka Micro)."""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import sqlite3
import struct
import sys
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tarka_core.internal_monitor import InternalMonitor

log = logging.getLogger("tarka_core.messaging")

_LOCK_HDR = struct.Struct("!II")  # subject_utf8_len, payload_len (max 4GiB each — truncated below)


def default_message_buffer_db_path() -> Path:
    """Canonical SQLite path for :class:`EphemeralDiskBufferBroker` / replay."""
    raw = (os.environ.get("TARKA_MESSAGE_BUFFER_DB") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "data" / "tarka_message_buffer.db").resolve()


def _appendonly_journal_path(db_path: Path) -> Path:
    return db_path.with_suffix(db_path.suffix + ".jlog")


@contextmanager
def _cross_process_publish_lock(lock_path: Path):
    """Exclusive OS lock so two processes never corrupt SQLite / journal writes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import msvcrt

        with open(lock_path, "a+b") as lf:
            lf.seek(0)
            try:
                msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lf.seek(0)
                msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        with open(lock_path, "a+b") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


CREATE_BUFFER_SQL = """
CREATE TABLE IF NOT EXISTS outbound_buffer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    payload BLOB NOT NULL,
    delivery TEXT NOT NULL,
    created_unix REAL NOT NULL,
    flushed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outbound_flushed ON outbound_buffer (flushed, id);
"""


def _sqlite_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=120.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(CREATE_BUFFER_SQL)
    return conn


def _sync_enqueue_with_lock(
    db_path: Path,
    lock_path: Path,
    journal_path: Path,
    subject: str,
    payload: bytes,
    delivery: str,
) -> int:
    """Insert one row + append length-prefixed record to journal (crash-safe dual trail). Returns row id."""
    subj_b = subject.encode("utf-8")
    if len(subj_b) > 1_048_576 or len(payload) > 16_777_216:
        raise ValueError("subject or payload exceeds safety bound")
    with _cross_process_publish_lock(lock_path):
        conn = _sqlite_connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO outbound_buffer (subject, payload, delivery, created_unix, flushed) VALUES (?,?,?,?,0)",
                (subject, sqlite3.Binary(payload), delivery, time.time()),
            )
            row_id = int(cur.lastrowid)
            conn.commit()
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception as rb_exc:
                InternalMonitor.log_suppressed_error(
                    rb_exc, context="sqlite_rollback_after_enqueue", domain="persistence"
                )
            raise
        finally:
            conn.close()
        # Append-only journal (same critical section as SQLite write)
        with open(journal_path, "ab") as jf:
            rec = _LOCK_HDR.pack(len(subj_b), len(payload)) + subj_b + payload
            jf.write(rec)
            jf.flush()
            os.fsync(jf.fileno())
    return row_id


def _sync_list_pending_ids(db_path: Path, lock_path: Path, limit: int) -> list[int]:
    with _cross_process_publish_lock(lock_path):
        conn = _sqlite_connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id FROM outbound_buffer WHERE flushed = 0 ORDER BY id ASC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return [int(r[0]) for r in rows]
        finally:
            conn.close()


def _sync_fetch_row(db_path: Path, lock_path: Path, row_id: int) -> tuple[str, bytes, str] | None:
    with _cross_process_publish_lock(lock_path):
        conn = _sqlite_connect(db_path)
        try:
            row = conn.execute(
                "SELECT subject, payload, delivery FROM outbound_buffer WHERE id = ? AND flushed = 0",
                (row_id,),
            ).fetchone()
            if row is None:
                return None
            return str(row[0]), bytes(row[1]), str(row[2])
        finally:
            conn.close()


def _sync_mark_flushed(db_path: Path, lock_path: Path, row_id: int) -> None:
    with _cross_process_publish_lock(lock_path):
        conn = _sqlite_connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE outbound_buffer SET flushed = 1 WHERE id = ?", (row_id,))
            conn.commit()
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception as rb_exc:
                InternalMonitor.log_suppressed_error(
                    rb_exc, context="sqlite_rollback_after_mark_flushed", domain="persistence"
                )
            raise
        finally:
            conn.close()


class PublishDelivery(enum.Enum):
    """NATS JetStream vs core publish (ignored by :class:`LocalAsyncBroker`)."""

    JETSTREAM = "jetstream"
    CORE = "core"


@dataclass(frozen=True, slots=True)
class DeadLetterMessage:
    """Queued when a subscriber callback raises (never silently dropped)."""

    subject: str
    payload: bytes
    error: str
    handler_repr: str


class MessageBroker(ABC):
    @abstractmethod
    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(
        self,
        subject: str,
        handler: Callable[[str, bytes], Awaitable[None]],
    ) -> Any:
        """Register ``handler`` for ``subject`` (exact match). Returns an opaque handle for optional unsubscribe."""

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError


def _coerce_delivery(raw: str) -> PublishDelivery:
    for m in PublishDelivery:
        if m.value == raw:
            return m
    return PublishDelivery.JETSTREAM


class EphemeralDiskBufferBroker(MessageBroker):
    """SQLite + append-only journal fallback when NATS/JetStream is unavailable.

    Survives process restarts; flush with :func:`replay_disk_buffer_to_broker` when a live broker is available.
    """

    __slots__ = ("_db_path", "_lock_path", "_journal_path", "_handlers", "_closed")

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = (
            Path(db_path).expanduser().resolve()
            if db_path is not None
            else default_message_buffer_db_path()
        )
        self._lock_path = self._db_path.with_suffix(self._db_path.suffix + ".lock")
        self._journal_path = _appendonly_journal_path(self._db_path)
        self._handlers: dict[str, list[Callable[[str, bytes], Awaitable[None]]]] = defaultdict(list)
        self._closed = False

    @property
    def buffer_db_path(self) -> Path:
        return self._db_path

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        if self._closed:
            raise RuntimeError("EphemeralDiskBufferBroker is closed")
        delivery_str = delivery.value
        await asyncio.to_thread(
            _sync_enqueue_with_lock,
            self._db_path,
            self._lock_path,
            self._journal_path,
            subject,
            payload,
            delivery_str,
        )
        for h in list(self._handlers.get(subject, ())):
            asyncio.create_task(self._invoke_handler(h, subject, payload))

    async def _invoke_handler(
        self,
        handler: Callable[[str, bytes], Awaitable[None]],
        subject: str,
        payload: bytes,
    ) -> None:
        try:
            await handler(subject, payload)
        except Exception:
            log.exception("EphemeralDiskBufferBroker subscriber raised subject=%s", subject)

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[str, bytes], Awaitable[None]],
    ) -> Any:
        self._handlers[subject].append(handler)
        return (subject, handler)

    async def unsubscribe(self, handle: Any) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        subj, fn = handle
        lst = self._handlers.get(subj)
        if not lst:
            return
        try:
            lst.remove(fn)  # type: ignore[arg-type]
        except ValueError:
            return
        if not lst:
            self._handlers.pop(subj, None)

    async def aclose(self) -> None:
        self._closed = True
        self._handlers.clear()


async def replay_disk_buffer_to_broker(
    db_path: Path | str | None,
    target: MessageBroker,
    *,
    batch_limit: int = 500,
) -> int:
    """Deliver pending buffered messages to ``target``, marking each row flushed after a successful publish.

    Returns the number of messages replayed. Stops on the first publish failure so nothing is marked flushed in error.
    """
    path = (
        Path(db_path).expanduser().resolve()
        if db_path is not None
        else default_message_buffer_db_path()
    )
    lock_path = path.with_suffix(path.suffix + ".lock")
    total = 0
    while True:
        ids = await asyncio.to_thread(_sync_list_pending_ids, path, lock_path, batch_limit)
        if not ids:
            return total
        for row_id in ids:
            row = await asyncio.to_thread(_sync_fetch_row, path, lock_path, row_id)
            if row is None:
                continue
            subj, payload, deliv_raw = row
            delivery = _coerce_delivery(deliv_raw)
            try:
                await target.publish(subj, payload, delivery=delivery)
            except Exception:
                log.exception(
                    "replay_disk_buffer_to_broker failed id=%s subject=%s; buffered rows retained",
                    row_id,
                    subj,
                )
                return total
            await asyncio.to_thread(_sync_mark_flushed, path, lock_path, row_id)
            total += 1


class NatsBroker(MessageBroker):
    """Wraps a connected ``nats.aio.client.Client`` (+ optional JetStream context)."""

    __slots__ = ("_nc", "_js")

    def __init__(self, nc: Any, js: Any | None = None) -> None:
        self._nc = nc
        self._js = js

    @property
    def has_active_connection(self) -> bool:
        return self._nc is not None

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        if delivery is PublishDelivery.CORE or self._js is None:
            await self._nc.publish(subject, payload)
            return
        await self._js.publish(subject, payload)

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[str, bytes], Awaitable[None]],
    ) -> Any:
        async def _cb(msg: Any) -> None:
            subj = getattr(msg, "subject", subject) or subject
            data = getattr(msg, "data", b"") or b""
            await handler(subj, data)

        return await self._nc.subscribe(subject, cb=_cb)

    async def aclose(self) -> None:
        nc = self._nc
        self._nc = None
        self._js = None
        if nc is not None:
            try:
                await nc.drain()
            except Exception:
                try:
                    await nc.close()
                except Exception as close_exc:
                    InternalMonitor.log_suppressed_error(
                        close_exc, context="nats_close_after_drain_failure", domain="messaging"
                    )


@dataclass(slots=True)
class _Outbound:
    subject: str
    payload: bytes


class LocalAsyncBroker(MessageBroker):
    """In-process pub/sub using bounded queues and worker tasks, with a dead-letter queue for handler failures."""

    __slots__ = (
        "_queue",
        "_dlq",
        "_handlers",
        "_workers",
        "_closing",
        "_started",
        "_max_queue",
        "_num_workers",
    )

    def __init__(self, *, num_workers: int = 4, max_queue_size: int = 10_000) -> None:
        self._num_workers = max(1, int(num_workers))
        self._max_queue = max(1, int(max_queue_size))
        self._queue: asyncio.Queue[_Outbound | None] = asyncio.Queue(maxsize=self._max_queue)
        self._dlq: asyncio.Queue[DeadLetterMessage] = asyncio.Queue()
        self._handlers: dict[str, list[Callable[[str, bytes], Awaitable[None]]]] = defaultdict(list)
        self._workers: list[asyncio.Task[None]] = []
        self._closing = asyncio.Event()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._closing.clear()
        for i in range(self._num_workers):
            self._workers.append(
                asyncio.create_task(self._worker_loop(i), name=f"tarka-local-broker-{i}")
            )

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        await self._queue.put(_Outbound(subject=subject, payload=payload))

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[str, bytes], Awaitable[None]],
    ) -> Any:
        self._handlers[subject].append(handler)
        return (subject, handler)

    async def unsubscribe(self, handle: Any) -> None:
        if not isinstance(handle, tuple) or len(handle) != 2:
            return
        subj, fn = handle
        lst = self._handlers.get(subj)
        if not lst:
            return
        try:
            lst.remove(fn)  # type: ignore[arg-type]
        except ValueError:
            return
        if not lst:
            self._handlers.pop(subj, None)

    async def drain_dead_letters(self) -> list[DeadLetterMessage]:
        """Test helper: drain the DLQ without blocking indefinitely."""
        out: list[DeadLetterMessage] = []
        while True:
            try:
                out.append(self._dlq.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def _worker_loop(self, worker_id: int) -> None:
        q = self._queue
        while True:
            if self._closing.is_set() and q.empty():
                return
            try:
                item = await asyncio.wait_for(q.get(), timeout=0.25)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            handlers = list(self._handlers.get(item.subject, ()))
            if not handlers:
                continue
            for h in handlers:
                try:
                    await h(item.subject, item.payload)
                except Exception as e:
                    dl = DeadLetterMessage(
                        subject=item.subject,
                        payload=item.payload,
                        error=f"{type(e).__name__}: {e}",
                        handler_repr=repr(h),
                    )
                    await self._dlq.put(dl)
                    log.warning(
                        "LocalAsyncBroker dead-letter subject=%s handler=%s error=%s",
                        item.subject,
                        dl.handler_repr,
                        dl.error,
                    )

    async def aclose(self) -> None:
        self._closing.set()
        for t in self._workers:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                continue
        self._workers.clear()
        self._started = False
