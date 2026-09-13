"""JetStream stream bootstrap for decision messages (A4 cold-start guard).

analytics-sink historically was the only service that created the
``FRAUD_DECISIONS`` stream. On cold start (or when analytics-sink is absent /
scaled to zero) decision-api's ``fraud.decisions.*`` publishes failed with
``NoStreamResponseError`` and decisions were silently dropped. Both sides now
ensure the stream idempotently; last-writer-wins is safe because both declare
identical config.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DECISIONS_STREAM_NAME = "FRAUD_DECISIONS"
DECISIONS_SUBJECT_FILTER = "fraud.decisions.>"
DECISIONS_MAX_MSGS = 10_000_000
DECISIONS_MAX_BYTES = 1024 * 1024 * 1024  # 1 GiB


async def ensure_decisions_stream(js: Any) -> None:
    """Idempotently ensure the FRAUD_DECISIONS stream covers fraud.decisions.>.

    Never raises: stream bootstrap failure must not block service startup.
    The publish path still logs (warning) when the stream is unavailable.
    """
    try:
        await js.find_stream_name_by_subject(DECISIONS_SUBJECT_FILTER)
        return
    except Exception:
        pass
    try:
        await js.add_stream(
            name=DECISIONS_STREAM_NAME,
            subjects=[DECISIONS_SUBJECT_FILTER],
            retention="limits",
            max_msgs=DECISIONS_MAX_MSGS,
            max_bytes=DECISIONS_MAX_BYTES,
        )
        logger.info("JetStream stream %s ensured", DECISIONS_STREAM_NAME)
    except Exception as exc:
        logger.warning("Could not ensure %s stream: %s", DECISIONS_STREAM_NAME, exc)
