"""Pluggable async messaging (NATS production, in-process broker for Tarka Micro)."""

from __future__ import annotations

import asyncio
import enum
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("tarka_core.messaging")


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


class NullMessageBroker(MessageBroker):
    """No-op broker when NATS is unavailable or not configured."""

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        delivery: PublishDelivery = PublishDelivery.JETSTREAM,
    ) -> None:
        return

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[str, bytes], Awaitable[None]],
    ) -> Any:
        return None

    async def aclose(self) -> None:
        return


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
                except Exception:
                    pass


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
            self._workers.append(asyncio.create_task(self._worker_loop(i), name=f"tarka-local-broker-{i}"))

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
            except asyncio.TimeoutError:
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
                pass
        self._workers.clear()
        self._started = False
