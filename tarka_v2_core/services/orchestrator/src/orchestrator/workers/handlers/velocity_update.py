"""Redis + ClickHouse velocity counter handler for ``VELOCITY_UPDATE`` outbox rows."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from orchestrator.analytics.velocity_counters import (
    apply_velocity_counter_increments,
    clickhouse_configured,
    ensure_velocity_counters_table,
)
from orchestrator.anumana_velocity import (
    apply_velocity_incrby_multi_exec,
    build_transaction_velocity_incrby_commands,
    ip_key_token,
)
from orchestrator.models.outbox import OUTBOX_EVENT_VELOCITY_UPDATE
from orchestrator.workers.handlers.base import BaseOutboxHandler

logger = logging.getLogger(__name__)


class VelocityUpdatePayloadError(ValueError):
    """Raised when a ``VELOCITY_UPDATE`` outbox payload is missing or invalid."""


def _parse_utc_timestamp_unix(ts_raw: object) -> int | None:
    if not isinstance(ts_raw, str):
        return None
    token = ts_raw.strip()
    if not token:
        return None
    try:
        dt = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VelocityUpdatePayloadError(f"invalid transaction_timestamp_utc: {token!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return int(dt.timestamp())


def _parse_amount_cents(raw: object) -> int:
    if raw is None:
        raise VelocityUpdatePayloadError("amount_cents is required in VELOCITY_UPDATE payload")
    try:
        amount_cents = int(raw)
    except (TypeError, ValueError) as exc:
        raise VelocityUpdatePayloadError(f"amount_cents must be an integer, got {raw!r}") from exc
    if amount_cents < 0:
        raise VelocityUpdatePayloadError("amount_cents must be >= 0")
    return amount_cents


def _ip_tokens_from_browser_context(ctx: dict[str, Any]) -> list[str]:
    ip_segments: list[str] = []
    for ip_raw in (
        ctx.get("ingress_ip"),
        ctx.get("client_claimed_ip"),
        ctx.get("ip"),
        ctx.get("ip_address"),
    ):
        if not isinstance(ip_raw, str):
            continue
        token = ip_raw.strip()
        if not token:
            continue
        seg = ip_key_token(token)
        if seg and seg not in ip_segments:
            ip_segments.append(seg)
    return ip_segments


def _parse_velocity_payload(
    payload: dict[str, Any],
) -> tuple[str, str | None, str | None, list[str], int, int | None]:
    if payload.get("schema") != "tarka.velocity_update.v1":
        raise VelocityUpdatePayloadError(
            f"unsupported velocity payload schema: {payload.get('schema')!r}",
        )

    entity_raw = payload.get("entity_id")
    if not isinstance(entity_raw, str) or not entity_raw.strip():
        raise VelocityUpdatePayloadError("entity_id is required in VELOCITY_UPDATE payload")
    entity_id = entity_raw.strip()

    ctx = payload.get("client_browser_metadata_context")
    browser_ctx = ctx if isinstance(ctx, dict) else {}

    device_raw = payload.get("device_hash_string")
    device_token: str | None = None
    if isinstance(device_raw, str) and device_raw.strip():
        device_token = device_raw.strip()

    tenant_raw = browser_ctx.get("tenant_id")
    tenant_id: str | None = None
    if isinstance(tenant_raw, str) and tenant_raw.strip():
        tenant_id = tenant_raw.strip()

    ip_tokens = _ip_tokens_from_browser_context(browser_ctx)
    amount_cents = _parse_amount_cents(payload.get("amount_cents"))
    now_unix = _parse_utc_timestamp_unix(payload.get("transaction_timestamp_utc"))
    return entity_id, device_token, tenant_id, ip_tokens, amount_cents, now_unix


class VelocityUpdateHandler(BaseOutboxHandler):
    """Apply transaction velocity counter increments in Redis and ClickHouse."""

    event_type = OUTBOX_EVENT_VELOCITY_UPDATE

    async def execute(self, payload: dict[str, Any]) -> None:
        if self._deps.redis_client is None:
            raise RuntimeError("ANUMANA_REDIS_URL is not configured for VELOCITY_UPDATE")
        if not isinstance(payload, dict):
            raise VelocityUpdatePayloadError("velocity payload must be a dict")

        entity_id, device_token, tenant_id, ip_tokens, amount_cents, now_unix = (
            _parse_velocity_payload(payload)
        )

        commands = build_transaction_velocity_incrby_commands(
            tenant_id=tenant_id,
            device_token=device_token,
            ip_tokens=ip_tokens,
            amount_cents=amount_cents,
            now_unix=now_unix,
        )
        if not commands:
            logger.info(
                "outbox_velocity_update_noop entity_id=%s reason=no_device_or_ip_segments",
                entity_id,
            )
            return

        await apply_velocity_incrby_multi_exec(self._deps.redis_client, commands)

        ch_client = self._deps.clickhouse_client
        if ch_client is None:
            if clickhouse_configured():
                raise RuntimeError(
                    "CLICKHOUSE_HOST/CLICKHOUSE_URL is set but ClickHouse client is unavailable for VELOCITY_UPDATE",
                )
            logger.debug(
                "outbox_velocity_update_clickhouse_skipped entity_id=%s reason=clickhouse_not_configured",
                entity_id,
            )
            return

        await asyncio.to_thread(
            _apply_clickhouse_increments_sync,
            ch_client,
            commands,
        )

        logger.info(
            "velocity_update_handler_completed entity_id=%s command_count=%s amount_cents=%s",
            entity_id,
            len(commands),
            amount_cents,
        )


def _apply_clickhouse_increments_sync(
    client: Any,
    commands: list[Any],
) -> None:
    ensure_velocity_counters_table(client)
    apply_velocity_counter_increments(client, commands)
