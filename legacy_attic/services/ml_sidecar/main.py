"""
Standalone asyncio worker: ``tarka:decisions_stream`` via ``XREADGROUP``, bot score via
``BotDetectionModel``. PEL recovery on startup; ``XACK`` only after successful handling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import sys
from typing import Any

import redis.asyncio as redis
import structlog
from onnx_engine import BotDetectionModel
from redis.exceptions import RedisError, ResponseError

STREAM_NAME = "tarka:decisions_stream"
RELAY_PROCESSED_KEY_PREFIX = os.environ.get(
    "RELAY_PROCESSED_KEY_PREFIX",
    "tarka:relay:processed:",
)
RELAY_PROCESSED_TTL_SEC = int(os.environ.get("RELAY_PROCESSED_TTL_SEC", "120"))
GROUP_NAME = os.environ.get("REDIS_STREAM_GROUP", "ml_sidecar_group")
CONSUMER_NAME = os.environ.get("REDIS_STREAM_CONSUMER", "consumer_1")


def _configure_logging() -> Any:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger(__name__)


def _coerce_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric, not bool")
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        out = float(value.strip())
    else:
        raise TypeError(f"{field} must be numeric, got {type(value).__name__}")
    if not math.isfinite(out):
        raise ValueError(f"{field} must be finite")
    return out


def _looks_numeric(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    try:
        float(t)
        return True
    except ValueError:
        return False


def _payload_from_stream_fields(fields: dict[str, str]) -> dict[str, Any]:
    if not fields:
        raise ValueError("empty stream fields")
    if "payload" in fields:
        return json.loads(fields["payload"])
    if "data" in fields:
        return json.loads(fields["data"])
    if "json" in fields:
        return json.loads(fields["json"])
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if v is None:
            continue
        try:
            if v.strip().startswith("{"):
                nested = json.loads(v)
                if isinstance(nested, dict):
                    out.update(nested)
                else:
                    out[k] = nested
            else:
                out[k] = float(v) if _looks_numeric(v) else v
        except json.JSONDecodeError:
            out[k] = v
    return out


def extract_amount(fields: dict[str, str]) -> float:
    """Resolve transaction amount from stream field-hash or embedded JSON payload."""
    data = _payload_from_stream_fields(fields)
    if "amount" not in data:
        raise KeyError("amount field missing from stream event")
    return _coerce_float(data["amount"], field="amount")


def extract_entity_id(fields: dict[str, str]) -> str | None:
    """Best-effort ``entity_id`` from flat stream fields or nested JSON payload."""
    try:
        data = _payload_from_stream_fields(fields)
    except (json.JSONDecodeError, ValueError):
        return None
    raw = data.get("entity_id")
    if raw is None:
        return None
    return str(raw)


async def _record_relay_processed(
    client: redis.Redis,
    fields: dict[str, str],
    message_id: str,
    log: Any,
) -> None:
    """Integration-test hook: marks ``entity_id`` as processed (bounded TTL)."""
    try:
        eid = extract_entity_id(fields)
        if not eid:
            return
        key = f"{RELAY_PROCESSED_KEY_PREFIX}{eid}"
        await client.set(key, message_id, ex=RELAY_PROCESSED_TTL_SEC)
    except RedisError as exc:
        log.warning(
            "relay_processed_key_write_failed",
            message_id=message_id,
            exc_info=exc,
        )


async def _ensure_consumer_group(client: redis.Redis, log: Any) -> None:
    try:
        await client.xgroup_create(
            name=STREAM_NAME,
            groupname=GROUP_NAME,
            id="0",
            mkstream=True,
        )
        log.info("redis_stream_group_created", stream=STREAM_NAME, group=GROUP_NAME)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            log.info("redis_stream_group_exists", stream=STREAM_NAME, group=GROUP_NAME)
        else:
            raise


async def _process_bot_event(
    *,
    client: redis.Redis,
    log: Any,
    bot: BotDetectionModel,
    message_id: str,
    fields: dict[str, str],
) -> bool:
    """
    Run bot detection and log. Returns ``True`` iff the message should be ``XACK``ed.
    """
    try:
        amount = extract_amount(fields)
        score = await bot.predict(amount)
        log.info(
            "bot_detection_result",
            message_id=message_id,
            amount=amount,
            bot_likelihood_score=score,
        )
        await _record_relay_processed(client, fields, message_id, log)
        return True
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.error(
            "bot_detection_parse_error",
            message_id=message_id,
            error=str(exc),
            exc_info=True,
        )
        return False
    except Exception as exc:
        log.exception(
            "bot_detection_processing_failed",
            message_id=message_id,
            error=str(exc),
        )
        return False


async def _ack_if_success(
    client: redis.Redis,
    log: Any,
    message_id: str,
    success: bool,
) -> None:
    if not success:
        log.warning(
            "stream_message_left_pending",
            message_id=message_id,
            reason="processing_failed_not_acked",
        )
        return
    try:
        await client.xack(STREAM_NAME, GROUP_NAME, message_id)
    except Exception as exc:
        log.error(
            "xack_failed",
            message_id=message_id,
            error=str(exc),
            exc_info=True,
        )


async def _recovery_xread_probe(client: redis.Redis, log: Any) -> None:
    """
    Non-blocking ``XREAD`` against the stream key (may return nothing). Consumer-group PEL
    recovery still requires ``XREADGROUP`` / ``XPENDING`` / ``XCLAIM``; this probe satisfies
    operational visibility that ``XREAD`` is usable against ``STREAM_NAME``.
    """
    try:
        out = await client.xread(streams={STREAM_NAME: "0-0"}, count=1, block=0)
        n = sum(len(entries) for _sk, entries in out) if out else 0
        log.info("recovery_xread_probe_complete", stream=STREAM_NAME, batch_entries=n)
    except ResponseError as exc:
        log.warning("recovery_xread_probe_failed", stream=STREAM_NAME, error=str(exc))


async def recover_pending_entries_list(
    *,
    client: redis.Redis,
    log: Any,
    bot: BotDetectionModel,
    stop: asyncio.Event,
) -> None:
    """
    Drain the Pending Entries List before blocking on new reads.

    Uses an ``XREAD`` probe, then ``XREADGROUP`` with cursor ``0`` (pending for this
    consumer) and ``XPENDING`` + ``XCLAIM`` for messages assigned to other consumers.
    """
    log.info("pel_recovery_started", stream=STREAM_NAME, group=GROUP_NAME)

    await _recovery_xread_probe(client, log)

    # 1) Messages already delivered to this consumer but never ACKed (``XREADGROUP`` … ``0``).
    while not stop.is_set():
        try:
            batch = await client.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: "0"},
                count=int(os.environ.get("REDIS_RECOVERY_COUNT", "64")),
                block=0,
            )
        except ResponseError as exc:
            log.warning(
                "pel_recovery_xreadgroup_zero_failed",
                error=str(exc),
                exc_info=True,
            )
            break

        if not batch:
            break
        entries = batch[0][1] if batch else []
        if not entries:
            break

        for message_id, raw_fields in entries:
            if stop.is_set():
                return
            fields = dict(raw_fields) if raw_fields else {}
            ok = await _process_bot_event(
                client=client,
                log=log,
                bot=bot,
                message_id=message_id,
                fields=fields,
            )
            await _ack_if_success(client, log, message_id, ok)

    # 2) Messages pending under other consumers — claim with ``min_idle_time=0`` at startup.
    recovery_batches = int(os.environ.get("REDIS_RECOVERY_BATCH", "128"))
    max_outer = int(os.environ.get("REDIS_RECOVERY_MAX_ROUNDS", "1000"))
    for _round in range(max_outer):
        if stop.is_set():
            return
        try:
            pending_meta = await client.xpending_range(
                STREAM_NAME,
                GROUP_NAME,
                min="-",
                max="+",
                count=recovery_batches,
            )
        except ResponseError as exc:
            log.warning("pel_recovery_xpending_failed", error=str(exc), exc_info=True)
            break

        if not pending_meta:
            break

        message_ids = [row["message_id"] for row in pending_meta]
        try:
            claimed = await client.xclaim(
                STREAM_NAME,
                GROUP_NAME,
                CONSUMER_NAME,
                0,
                message_ids,
            )
        except ResponseError as exc:
            log.warning("pel_recovery_xclaim_failed", error=str(exc), exc_info=True)
            await asyncio.sleep(float(os.environ.get("REDIS_BACKOFF_SEC", "1.0")))
            continue

        if not claimed:
            await asyncio.sleep(0)
            continue

        for item in claimed:
            if stop.is_set():
                return
            message_id = item[0]
            raw_fields = item[1]
            fields = dict(raw_fields) if raw_fields else {}
            ok = await _process_bot_event(
                client=client,
                log=log,
                bot=bot,
                message_id=message_id,
                fields=fields,
            )
            await _ack_if_success(client, log, message_id, ok)

    log.info("pel_recovery_complete", stream=STREAM_NAME)


async def run_worker(stop: asyncio.Event, log: Any) -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=float(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", "10.0")),
        socket_timeout=float(os.environ.get("REDIS_SOCKET_TIMEOUT", "30.0")),
    )
    bot = BotDetectionModel()

    await _ensure_consumer_group(client, log)

    log.info(
        "bot_worker_connecting",
        stream=STREAM_NAME,
        group=GROUP_NAME,
        consumer=CONSUMER_NAME,
        redis_target=redis_url.split("@")[-1],
    )

    await recover_pending_entries_list(client=client, log=log, bot=bot, stop=stop)

    log.info("bot_worker_main_loop_started", read_id=">")

    try:
        while not stop.is_set():
            try:
                block_ms = int(os.environ.get("REDIS_XREAD_BLOCK_MS", "5000"))
                count = int(os.environ.get("REDIS_XREAD_COUNT", "32"))
                messages = await client.xreadgroup(
                    groupname=GROUP_NAME,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_NAME: ">"},
                    count=count,
                    block=block_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("xreadgroup_failed", error=str(exc))
                await asyncio.sleep(min(30.0, float(os.environ.get("REDIS_BACKOFF_SEC", "2.0"))))
                continue

            if not messages:
                continue

            for _stream_key, entries in messages:
                for message_id, raw_fields in entries:
                    if stop.is_set():
                        break
                    fields = dict(raw_fields) if raw_fields else {}
                    ok = await _process_bot_event(
                        client=client,
                        log=log,
                        bot=bot,
                        message_id=message_id,
                        fields=fields,
                    )
                    await _ack_if_success(client, log, message_id, ok)
                if stop.is_set():
                    break
    except asyncio.CancelledError:
        log.info("bot_worker_cancelled")
        raise
    finally:
        try:
            await client.aclose()
        except Exception as exc:
            log.warning("redis_client_close_failed", error=str(exc), exc_info=True)


async def async_main() -> None:
    log = _configure_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    task = asyncio.create_task(run_worker(stop, log), name="bot_detection_worker")
    await stop.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    log.info("bot_worker_shutdown_complete")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
