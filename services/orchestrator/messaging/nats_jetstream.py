"""NATS JetStream bootstrap for orchestrator domain events (``TARKA_EVENTS`` stream)."""

from __future__ import annotations

import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

TARKA_EVENTS_STREAM_NAME = "TARKA_EVENTS"

TARKA_EVENTS_SUBJECTS: tuple[str, ...] = (
    "tarka.events.graph",
    "tarka.events.velocity",
    "tarka.events.labels",
)

_DEFAULT_MAX_AGE_SEC = 7 * 24 * 3600  # 7 days
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB


class JetStreamUnavailableError(RuntimeError):
    """Raised when the broker has no usable JetStream context."""


def _resolve_nats_url(explicit: str | None) -> str:
    url = (explicit or get_settings().nats_url or "").strip()
    if not url:
        raise RuntimeError("NATS_URL is required for JetStream initialization")
    return url


def _resolve_max_age_sec(explicit: float | None) -> float:
    if explicit is not None:
        if explicit <= 0:
            raise ValueError(f"max_age_sec must be > 0, got {explicit}")
        return float(explicit)
    return float(get_settings().tarka_events_jetstream_max_age_sec)


def _resolve_max_bytes(explicit: int | None) -> int:
    if explicit is not None:
        if explicit <= 0:
            raise ValueError(f"max_bytes must be > 0, got {explicit}")
        return int(explicit)
    return int(get_settings().tarka_events_jetstream_max_bytes)


class TarkaEventsJetStreamInitializer:
    """
    Connect to NATS, verify JetStream, and declare the ``TARKA_EVENTS`` stream.

    Uses ``StreamConfig.RetentionPolicy.LIMITS`` so messages are retained until
    ``max_age`` or ``max_bytes`` pruning limits are reached (at-least-once consumer acks).
    """

    def __init__(
        self,
        *,
        nats_url: str | None = None,
        max_age_sec: float | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self._nats_url = _resolve_nats_url(nats_url)
        self._max_age_sec = _resolve_max_age_sec(max_age_sec)
        self._max_bytes = _resolve_max_bytes(max_bytes)
        self._nc: Any | None = None
        self._js: Any | None = None

    @classmethod
    def from_environment(cls) -> TarkaEventsJetStreamInitializer:
        return cls()

    @property
    def nats_client(self) -> Any:
        if self._nc is None:
            raise RuntimeError("NATS client is not connected; call connect() first")
        return self._nc

    @property
    def jetstream(self) -> Any:
        if self._js is None:
            raise RuntimeError("JetStream context is not available; call connect() first")
        return self._js

    def stream_config(self) -> Any:
        from nats.js.api import RetentionPolicy, StorageType, StreamConfig  # noqa: PLC0415

        return StreamConfig(
            name=TARKA_EVENTS_STREAM_NAME,
            subjects=list(TARKA_EVENTS_SUBJECTS),
            retention=RetentionPolicy.LIMITS,
            max_age=self._max_age_sec,
            max_bytes=self._max_bytes,
            storage=StorageType.FILE,
        )

    async def ensure_streams_on(self, js: Any) -> None:
        """Declare or update ``TARKA_EVENTS`` on an existing JetStream context (shared NATS connection)."""
        self._js = js
        await self._assert_jetstream_available()
        await self._ensure_tarka_events_stream()
        logger.info(
            "tarka_events_jetstream_ready stream=%s subjects=%s max_age_sec=%s max_bytes=%s",
            TARKA_EVENTS_STREAM_NAME,
            ",".join(TARKA_EVENTS_SUBJECTS),
            self._max_age_sec,
            self._max_bytes,
        )

    async def connect(self) -> None:
        """Connect to NATS, assert JetStream, and create or update ``TARKA_EVENTS``."""
        try:
            import nats  # noqa: PLC0415 — ``pip install tarka-orchestrator[worker]``
        except ImportError as exc:
            raise RuntimeError(
                "nats-py is required for JetStream initialization (pip install tarka-orchestrator[worker])",
            ) from exc

        self._nc = await nats.connect(self._nats_url)
        js = self._nc.jetstream()
        if js is None:
            await self._close_quietly()
            raise JetStreamUnavailableError("nc.jetstream() returned no JetStream context")
        self._js = js

        try:
            await self._assert_jetstream_available()
            await self._ensure_tarka_events_stream()
        except Exception:
            await self._close_quietly()
            raise

        logger.info(
            "tarka_events_jetstream_ready stream=%s subjects=%s max_age_sec=%s max_bytes=%s",
            TARKA_EVENTS_STREAM_NAME,
            ",".join(TARKA_EVENTS_SUBJECTS),
            self._max_age_sec,
            self._max_bytes,
        )

    async def close(self) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.drain()
        except Exception:
            logger.exception("tarka_events_jetstream_drain_failed")
        finally:
            self._nc = None
            self._js = None

    async def _close_quietly(self) -> None:
        nc = self._nc
        self._nc = None
        self._js = None
        if nc is None:
            return
        try:
            await nc.drain()
        except Exception:
            logger.debug("tarka_events_jetstream_connect_cleanup_drain_failed", exc_info=True)

    async def _assert_jetstream_available(self) -> None:
        assert self._js is not None
        try:
            await self._js.account_info()
        except Exception as exc:
            raise JetStreamUnavailableError(
                "NATS broker did not expose a usable JetStream account (is --jetstream enabled?)",
            ) from exc

    async def _ensure_tarka_events_stream(self) -> None:
        from nats.js.errors import NotFoundError  # noqa: PLC0415

        assert self._js is not None
        config = self.stream_config()
        try:
            await self._js.stream_info(TARKA_EVENTS_STREAM_NAME)
        except NotFoundError:
            await self._js.add_stream(config)
            logger.info(
                "tarka_events_jetstream_stream_created name=%s retention=LIMITS",
                TARKA_EVENTS_STREAM_NAME,
            )
            return

        await self._js.update_stream(config)
        logger.info(
            "tarka_events_jetstream_stream_updated name=%s retention=LIMITS",
            TARKA_EVENTS_STREAM_NAME,
        )
