"""GRAPH_INGEST outbox handler: post contract objects to graph-service."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from ingestor.manifest_schema import TransactionSchema

from graph.client import graph_hints_from_event
from models.outbox import OUTBOX_EVENT_GRAPH_INGEST
from workers.handlers.base import BaseOutboxHandler

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_SERVICE_URL = "http://graph-service:8001"

_OBJECT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("device_id", "device_id", "device", "USED_DEVICE"),
    ("ip", "address", "ip", "USED_IP"),
    ("card_id", "card_id", "payment", "MADE_PAYMENT"),
)


class GraphDatabaseConnectionError(ConnectionError):
    """Raised when graph-service rejects or drops a GRAPH_INGEST post."""


class GraphIngestPayloadError(ValueError):
    """Raised when a ``GRAPH_INGEST`` outbox payload is missing required fields."""


def _parse_audit_log_id(payload: dict[str, Any]) -> int:
    raw = payload.get("audit_log_id")
    if raw is None:
        raise GraphIngestPayloadError("audit_log_id is required in GRAPH_INGEST payload")
    try:
        audit_log_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise GraphIngestPayloadError(f"audit_log_id must be an integer, got {raw!r}") from exc
    if audit_log_id < 1:
        raise GraphIngestPayloadError("audit_log_id must be >= 1")
    return audit_log_id


def _parse_transaction(payload: dict[str, Any]) -> TransactionSchema:
    envelope = payload.get("edge_transaction_payload_envelope")
    if not isinstance(envelope, dict):
        raise GraphIngestPayloadError("edge_transaction_payload_envelope missing or not an object")
    return TransactionSchema.model_validate(envelope)


def _event_from_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("event")
    if isinstance(raw, dict):
        return {
            "tenant_id": str(raw.get("tenant_id") or "").strip(),
            "entity_id": str(raw.get("entity_id") or "").strip(),
            "event_type": str(raw.get("event_type") or "payment").strip() or "payment",
            "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        }
    envelope = payload.get("edge_transaction_payload_envelope")
    if not isinstance(envelope, dict):
        raise GraphIngestPayloadError("event or edge_transaction_payload_envelope is required")
    meta = envelope.get("metadata") if isinstance(envelope.get("metadata"), dict) else {}
    return {
        "tenant_id": str(meta.get("tenant_id") or "").strip(),
        "entity_id": str(envelope.get("entity_id") or "").strip(),
        "event_type": str(meta.get("event_type") or "payment").strip() or "payment",
        "payload": {
            "amount": envelope.get("amount"),
            "timestamp": envelope.get("timestamp"),
            "country": envelope.get("country"),
        },
        "metadata": meta,
    }


def posts_for_hints(hints: dict[str, Any]) -> list[dict[str, Any]]:
    tenant = str(hints.get("tenant_id") or "").strip()
    user_id = str(hints.get("user_id") or "").strip()
    if not tenant or not user_id:
        return []
    bodies: list[dict[str, Any]] = []
    for source_key, object_field, object_type, relationship in _OBJECT_SPECS:
        value = str(hints.get(source_key) or "").strip()
        if not value:
            continue
        bodies.append(
            {
                "tenant_id": tenant,
                "source": "orchestrator",
                "mapping": {
                    "join_field": "user_id",
                    "object_field": object_field,
                    "object_type": object_type,
                    "relationship": relationship,
                },
                "record": {"user_id": user_id, object_field: value},
            }
        )
    return bodies


def _graph_service_url() -> str:
    raw = (os.environ.get("GRAPH_SERVICE_URL") or _DEFAULT_GRAPH_SERVICE_URL).strip()
    return (raw or _DEFAULT_GRAPH_SERVICE_URL).rstrip("/")


class GraphIngestHandler(BaseOutboxHandler):
    """Post GRAPH_INGEST rows to graph-service ``/v1/ingest/objects``."""

    event_type = OUTBOX_EVENT_GRAPH_INGEST

    async def execute(self, payload: dict[str, Any]) -> str | None:
        if not isinstance(payload, dict):
            raise GraphIngestPayloadError("graph ingest payload must be a dict")

        audit_log_id = _parse_audit_log_id(payload)
        event = _event_from_graph_payload(payload)
        if not event["tenant_id"]:
            logger.info(
                "graph_ingest_noop entity_id=%s audit_log_id=%s reason=no_tenant",
                event.get("entity_id"),
                audit_log_id,
            )
            return "noop:no_tenant"

        hints = graph_hints_from_event(event)
        bodies = posts_for_hints(
            {
                "tenant_id": event["tenant_id"],
                "user_id": hints.user_id,
                "device_id": hints.device_id,
                "ip": hints.ip,
                "card_id": hints.card_id,
                "email": hints.email,
                "address": hints.address,
            }
        )
        if not bodies:
            logger.info(
                "graph_ingest_noop entity_id=%s audit_log_id=%s reason=no_graph_hints",
                event.get("entity_id"),
                audit_log_id,
            )
            return "noop:no_graph_hints"

        url = f"{_graph_service_url()}/v1/ingest/objects"
        async with httpx.AsyncClient(timeout=5.0) as http:
            for body in bodies:
                response = await http.post(url, json=body)
                if response.status_code != 200:
                    raise GraphDatabaseConnectionError(
                        f"graph-service ingest failed status={response.status_code}"
                    )

        logger.info(
            "graph_ingest_handler_completed entity_id=%s audit_log_id=%s posts=%s",
            event.get("entity_id"),
            audit_log_id,
            len(bodies),
        )
        return None
