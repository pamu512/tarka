"""Map Redis ``tarka.browser_telemetry.v1`` JSON envelopes to :class:`~ingestor.manifest_schema.TransactionSchema`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ingestor.manifest_schema import TransactionSchema


def _parse_ts(raw: str | None) -> datetime:
    if not raw or not str(raw).strip():
        return datetime.now(UTC)
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def sdk_browser_envelope_to_transaction(envelope: dict[str, Any]) -> TransactionSchema:
    """
    Deterministic ``entity_id`` from envelope payload hash so duplicate Redis deliveries skew analytics
    less catastrophically; nominal ``amount=1.0`` satisfies strict positivity.
    """
    schema = envelope.get("schema")
    if schema != "tarka.browser_telemetry.v1":
        raise ValueError(f"unsupported envelope schema: {schema!r}")

    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    entity_id = uuid5(NAMESPACE_URL, f"tarka:sdk_telemetry:{canonical}")

    ts = _parse_ts(envelope.get("ts"))
    tenant_id = envelope.get("tenant_id")
    canvas = envelope.get("canvas_fingerprint")
    ingress_ip = envelope.get("ingress_ip")
    client_ip = envelope.get("client_claimed_ip")

    meta: dict[str, Any] = {
        "sdk_source": "browser_telemetry",
        "tenant_id": tenant_id,
        "canvas_fingerprint": canvas,
        "ingress_ip": ingress_ip,
        "client_claimed_ip": client_ip,
        "device_session_id": envelope.get("device_session_id"),
        "canvas_raster_digest_hex": envelope.get("canvas_raster_digest_hex"),
        "telemetry_packet": envelope.get("telemetry_packet"),
        "country": "ZZ",
    }

    return TransactionSchema(
        entity_id=entity_id,
        amount=1.0,
        timestamp=ts,
        metadata=meta,
        country="ZZ",
    )


def parse_envelope_bytes(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("envelope must be a JSON object")
    return data


def envelope_bytes_to_transaction(raw: bytes) -> TransactionSchema:
    return sdk_browser_envelope_to_transaction(parse_envelope_bytes(raw))
