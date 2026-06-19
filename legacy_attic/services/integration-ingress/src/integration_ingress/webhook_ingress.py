"""KYC webhook normalization, DLQ logging, and inbox persistence helpers."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.adapters import ADAPTERS
from integration_ingress.models import WebhookInbox

logger = logging.getLogger(__name__)

WEBHOOK_NORMALIZATION_FAILED_DETAIL = "Webhook payload normalization failed"

_FATAL_NORMALIZATION_ERRORS = (
    TypeError,
    KeyError,
    ValueError,
    json.JSONDecodeError,
)


def log_webhook_dlq(
    *,
    provider: str,
    event_id: uuid.UUID,
    payload: dict[str, Any],
    error: str,
) -> None:
    """Structured dead-letter log for webhook payloads that cannot be normalized."""
    keys: list[str] = []
    if isinstance(payload, dict):
        keys = sorted(str(k) for k in payload.keys())[:32]
    logger.error(
        "webhook_dlq provider=%s event_id=%s error=%s payload_key_count=%s payload_keys=%s",
        provider,
        event_id,
        error,
        len(payload) if isinstance(payload, dict) else 0,
        keys,
    )


def _raise_normalization_http(
    *,
    provider: str,
    event_id: uuid.UUID,
    payload: dict[str, Any],
    error: str,
    cause: BaseException | None = None,
) -> None:
    log_webhook_dlq(provider=provider, event_id=event_id, payload=payload, error=error)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=WEBHOOK_NORMALIZATION_FAILED_DETAIL,
    ) from cause


async def normalize_kyc_webhook_payload(
    *,
    provider: str,
    payload: dict[str, Any],
    event_id: uuid.UUID,
) -> dict[str, Any]:
    """Run the registered KYC adapter; raise HTTP 422 and DLQ-log on failure."""
    adapter_fn = ADAPTERS.get(provider)
    if adapter_fn is None:
        _raise_normalization_http(
            provider=provider,
            event_id=event_id,
            payload=payload,
            error="unknown_provider",
        )

    try:
        normalized = await adapter_fn("", "", payload)
    except _FATAL_NORMALIZATION_ERRORS as exc:
        _raise_normalization_http(
            provider=provider,
            event_id=event_id,
            payload=payload,
            error=f"fatal_payload:{type(exc).__name__}:{exc}",
            cause=exc,
        )
    except Exception:
        logger.exception(
            "webhook_adapter_unexpected provider=%s event_id=%s",
            provider,
            event_id,
        )
        raise

    if not isinstance(normalized, dict):
        _raise_normalization_http(
            provider=provider,
            event_id=event_id,
            payload=payload,
            error="normalized_not_object",
        )

    return normalized


async def persist_failed_webhook(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    provider: str,
    payload: dict[str, Any],
    error: str,
) -> WebhookInbox:
    """Insert an inbox row with status ``normalization_failed`` so the audit trail is preserved."""
    log_webhook_dlq(provider=provider, event_id=event_id, payload=payload, error=error)
    record = WebhookInbox(
        id=event_id,
        provider=provider,
        raw_payload=payload,
        normalized=None,
        status="normalization_failed",
    )
    session.add(record)
    await session.commit()
    return record


async def persist_normalized_webhook(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    provider: str,
    payload: dict[str, Any],
    normalized: dict[str, Any],
) -> WebhookInbox:
    """Insert a normalized inbox row and commit (downstream workers read ``status=normalized``)."""
    record = WebhookInbox(
        id=event_id,
        provider=provider,
        raw_payload=payload,
        normalized=normalized,
        status="normalized",
    )
    session.add(record)
    await session.commit()
    return record
