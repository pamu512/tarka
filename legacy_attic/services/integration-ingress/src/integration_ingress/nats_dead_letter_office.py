"""Peek JetStream ingest DLQ messages for the Dead Letter Office UI (Prompt 171)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_PEEK_DURABLE = "integration-ingress-dlq-office-peek"


def _dlq_config() -> tuple[str, str, str]:
    subject = (os.environ.get("INGEST_DLQ_SUBJECT") or os.environ.get("NATS_DLQ_SUBJECT") or "fraud.events.dlq").strip()
    stream = (os.environ.get("NATS_STREAM_NAME") or os.environ.get("INGEST_STREAM_NAME") or "FRAUD_EVENTS").strip()
    prefix = (os.environ.get("INGEST_SUBJECT_PREFIX") or "fraud.events").strip()
    return subject, stream, prefix


def _parse_envelope(raw: bytes, *, subject: str, sequence: int) -> dict[str, Any]:
    preview = raw[:240].decode("utf-8", errors="replace")
    item: dict[str, Any] = {
        "id": f"{sequence}",
        "sequence": sequence,
        "subject": subject,
        "received_at": None,
        "kind": "unknown",
        "status_code": None,
        "tenant_id": None,
        "entity_id": None,
        "event_type": None,
        "nats_source_subject": None,
        "preview": preview,
        "envelope": {},
    }
    try:
        data = json.loads(raw.decode())
    except json.JSONDecodeError:
        item["kind"] = "invalid_json"
        return item
    if not isinstance(data, dict):
        item["kind"] = "invalid_envelope"
        return item
    item["envelope"] = data
    item["kind"] = str(data.get("kind") or "unknown")
    sc = data.get("status_code")
    item["status_code"] = int(sc) if isinstance(sc, (int, float)) else None
    item["nats_source_subject"] = str(data.get("nats_source_subject") or "") or None
    ev = data.get("event")
    req = data.get("evaluate_request")
    src = ev if isinstance(ev, dict) else req if isinstance(req, dict) else data
    if isinstance(src, dict):
        item["tenant_id"] = str(src.get("tenant_id") or "") or None
        item["entity_id"] = str(src.get("entity_id") or "") or None
        item["event_type"] = str(src.get("event_type") or "") or None
    item["preview"] = json.dumps(data, default=str)[:240]
    return item


async def build_nats_dead_letter_office_payload(
    *,
    nats_nc: Any | None,
    limit: int = 100,
    kind_filter: str | None = None,
    tenant_filter: str | None = None,
) -> dict[str, Any]:
    """Non-destructive peek: fetch DLQ batch then NAK so messages remain on the stream."""
    subject, stream, prefix = _dlq_config()
    lim = max(1, min(int(limit), 500))
    kind_f = (kind_filter or "").strip().lower()
    tenant_f = (tenant_filter or "").strip().lower()

    base: dict[str, Any] = {
        "stream_name": stream,
        "dlq_subject": subject,
        "subject_prefix": prefix,
        "nats_connected": False,
        "jetstream_enabled": False,
        "pending_estimate": None,
        "items": [],
        "peeked_at": datetime.now(UTC).isoformat(),
        "source": "live",
    }

    if nats_nc is None:
        return base

    try:
        nats_ok = bool(nats_nc.is_connected)
    except Exception:
        nats_ok = False
    base["nats_connected"] = nats_ok
    if not nats_ok:
        return base

    try:
        js = await nats_nc.jetstream()
        base["jetstream_enabled"] = True
    except Exception as exc:
        logger.debug("dlq office jetstream unavailable: %s", exc)
        return base

    try:
        info = await js.stream_info(stream)
        base["pending_estimate"] = int(getattr(info.state, "messages", 0) or 0)
    except Exception:
        base["pending_estimate"] = None

    items: list[dict[str, Any]] = []
    try:
        sub = await js.pull_subscribe(subject, durable=_PEEK_DURABLE, stream=stream)
        fetched = await sub.fetch(batch=lim, timeout=2.0)
        for msg in fetched:
            seq = 0
            meta = getattr(msg, "metadata", None)
            if meta is not None:
                seq = int(getattr(meta, "sequence", None) or getattr(meta, "sequence_stream", 0) or 0)
            subj = str(getattr(msg, "subject", None) or subject)
            row = _parse_envelope(msg.data, subject=subj, sequence=seq)
            if kind_f and (row.get("kind") or "").lower() != kind_f:
                await msg.nak(delay=1)
                continue
            if tenant_f:
                tid = str(row.get("tenant_id") or "").lower()
                if tenant_f not in tid:
                    await msg.nak(delay=1)
                    continue
            items.append(row)
            await msg.nak(delay=1)
    except Exception as exc:
        logger.warning("dlq office peek failed: %s", exc)
        base["error"] = str(exc)[:500]

    base["items"] = items
    return base
