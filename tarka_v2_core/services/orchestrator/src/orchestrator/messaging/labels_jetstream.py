"""Publish enriched ``normalized_labels`` entities to ``tarka.events.labels`` JetStream."""

from __future__ import annotations

import json
import logging
from typing import Any

from orchestrator.config import get_settings
from orchestrator.messaging.nats_jetstream import TARKA_EVENTS_STREAM_NAME

logger = logging.getLogger(__name__)

TARKA_LABELS_SUBJECT = "tarka.events.labels"
NORMALIZED_LABEL_EVENT_SCHEMA = "tarka.normalized_label.v1"


def consortium_labels_durable_name() -> str:
    return get_settings().consortium_labels_jetstream_durable


def consortium_labels_fetch_batch_size() -> int:
    return get_settings().consortium_labels_jetstream_fetch_batch


class LabelsJetStreamPublishError(RuntimeError):
    """Raised when a label event cannot be published to JetStream."""


def normalized_label_event_entity(row: Any) -> dict[str, Any]:
    """Serialize a :class:`~orchestrator.models.normalized_labels.NormalizedLabelORM` row for NATS."""
    created_at = getattr(row, "created_at", None)
    created_iso = created_at.isoformat() if created_at is not None else None
    return {
        "schema": NORMALIZED_LABEL_EVENT_SCHEMA,
        "id": str(getattr(row, "id")),
        "source_type": str(getattr(row, "source_type")),
        "source_id": str(getattr(row, "source_id")),
        "entity_id": str(getattr(row, "entity_id")),
        "ground_truth_class": str(getattr(row, "ground_truth_class")),
        "tags": list(getattr(row, "tags") or []),
        "propagated_to_consortium": bool(getattr(row, "propagated_to_consortium", False)),
        "created_at": created_iso,
    }


def decode_normalized_label_event(msg: Any) -> dict[str, Any]:
    """Parse a JetStream message body into a normalized label event dict."""
    raw = getattr(msg, "data", None)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def publish_normalized_label_enriched(
    jetstream: Any,
    *,
    label_entity: dict[str, Any],
) -> None:
    """Emit the full enriched label entity onto ``tarka.events.labels``."""
    if jetstream is None:
        raise LabelsJetStreamPublishError("JetStream client is required to publish label events")

    label_id = str(label_entity.get("id") or "").strip()
    if not label_id:
        raise LabelsJetStreamPublishError("label_entity.id is required for JetStream publish")

    body = json.dumps(label_entity, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers: dict[str, str] | None = None
    if label_id:
        headers = {"Nats-Msg-Id": f"normalized-label:{label_id}"}

    try:
        if headers is not None:
            await jetstream.publish(TARKA_LABELS_SUBJECT, body, headers=headers)
        else:
            await jetstream.publish(TARKA_LABELS_SUBJECT, body)
    except Exception as exc:
        raise LabelsJetStreamPublishError(
            f"failed to publish normalized label {label_id!r} to {TARKA_LABELS_SUBJECT}",
        ) from exc

    logger.info(
        "normalized_label_jetstream_published subject=%s stream=%s label_id=%s tag_count=%s",
        TARKA_LABELS_SUBJECT,
        TARKA_EVENTS_STREAM_NAME,
        label_id,
        len(label_entity.get("tags") or []),
    )
