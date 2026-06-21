"""JetStream stream declaration for durable ``shadow.investigate`` handoff."""

from __future__ import annotations

import logging
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)


def shadow_investigate_stream_name() -> str:
    return get_settings().shadow_investigate_jetstream_stream


def shadow_investigate_durable_name() -> str:
    return get_settings().shadow_investigate_jetstream_durable


def shadow_investigate_fetch_batch_size() -> int:
    return get_settings().shadow_investigate_jetstream_fetch_batch


def _resolve_max_age_sec() -> float:
    return float(get_settings().shadow_investigate_jetstream_max_age_sec)


def _resolve_max_bytes() -> int:
    return int(get_settings().shadow_investigate_jetstream_max_bytes)


async def ensure_shadow_investigate_stream(js: Any, *, subject: str) -> None:
    """Create or update the JetStream stream covering ``shadow.investigate``."""
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig  # noqa: PLC0415
    from nats.js.errors import NotFoundError  # noqa: PLC0415

    stream_name = shadow_investigate_stream_name()
    subj = subject.strip()
    if not subj:
        raise ValueError("subject is required for shadow investigate stream")

    config = StreamConfig(
        name=stream_name,
        subjects=[subj],
        retention=RetentionPolicy.LIMITS,
        max_age=_resolve_max_age_sec(),
        max_bytes=_resolve_max_bytes(),
        storage=StorageType.FILE,
    )
    try:
        await js.stream_info(stream_name)
    except NotFoundError:
        await js.add_stream(config)
        logger.info(
            "shadow_investigate_jetstream_stream_created name=%s subject=%s retention=LIMITS",
            stream_name,
            subj,
        )
        return

    await js.update_stream(config)
    logger.info(
        "shadow_investigate_jetstream_stream_updated name=%s subject=%s retention=LIMITS",
        stream_name,
        subj,
    )
