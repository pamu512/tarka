"""Decode wire EvidenceManifest protobuf into ClickHouse row primitives."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from google.protobuf.message import DecodeError

from ingestor.manifest_schema import validate_manifest_against_registry
from ingestor.settings import IngestorSettings
from tarka.evidence.wire.v1 import evidence_pb2


class ManifestDecodeError(ValueError):
    """Raised when protobuf bytes cannot be parsed as EvidenceManifest."""


def _wire_signal_value_to_str(value: evidence_pb2.SignalValue) -> str:
    which = value.WhichOneof("value")
    if which == "bool_val":
        return "true" if value.bool_val else "false"
    if which == "num_val":
        return repr(value.num_val)
    if which == "str_val":
        return value.str_val
    if which == "raw_bytes":
        return value.raw_bytes.hex()
    return ""


def parse_evidence_manifest(raw: bytes) -> evidence_pb2.EvidenceManifest:
    """Parse raw bytes into wire EvidenceManifest (syntax only)."""
    msg = evidence_pb2.EvidenceManifest()
    try:
        msg.ParseFromString(raw)
    except DecodeError as exc:
        raise ManifestDecodeError("invalid EvidenceManifest protobuf") from exc
    return msg


def decode_manifest_row(
    raw: bytes,
    *,
    settings: IngestorSettings | None = None,
) -> dict[str, Any]:
    """Parse protobuf, enforce schema registry rules, return dict aligned with ClickHouse ``evidence_manifests`` columns (includes ``tenant_id``)."""
    msg = parse_evidence_manifest(raw)
    cfg = settings if settings is not None else IngestorSettings()
    validate_manifest_against_registry(msg, cfg)
    return _manifest_to_row(msg, raw, tenant_id=cfg.tenant_id)


def _final_decision_from_verdict(msg: evidence_pb2.EvidenceManifest) -> int:
    if not msg.HasField("verdict"):
        return 0
    action = msg.verdict.action
    if action in ("pass", "partial_allow"):
        return 1
    if action in ("fail", "partial_deny"):
        return 0
    return 1 if action == "pass" else 0


def _total_execution_time_us(msg: evidence_pb2.EvidenceManifest) -> int:
    if not msg.HasField("verdict"):
        return 0
    return int(msg.verdict.latency_ns // 1000)


def _manifest_to_row(
    msg: evidence_pb2.EvidenceManifest, raw: bytes, *, tenant_id: str
) -> dict[str, Any]:
    try:
        manifest_uuid = uuid.UUID(msg.manifest_id)
    except ValueError as exc:
        raise ManifestDecodeError("manifest_id must be a UUID string") from exc

    signals: dict[str, str] = {}
    for key, sig in msg.signals.items():
        signals[key] = _wire_signal_value_to_str(sig)

    trace_steps: list[dict[str, Any]] = []
    for step in msg.trace:
        snap = dict(step.state_snapshot.items())
        trace_steps.append(
            {
                "rule_id": step.rule_id,
                "logic_operator": step.operator,
                "operands": list(step.operands),
                "result": bool(step.result),
                "state_snapshot": snap,
                "otel_trace_id": "",
            }
        )

    sig_bytes = bytes(msg.signature) if msg.signature else b""
    sig_hex = sig_bytes.hex()
    crypto_algorithm = "ed25519ph" if sig_bytes else "none"

    raw_digest = hashlib.sha256(raw).digest()

    engine_version = msg.engine.version if msg.HasField("engine") else ""

    return {
        "tenant_id": tenant_id,
        "manifest_id": manifest_uuid,
        "engine_version": engine_version,
        "timestamp_ns": int(msg.occurred_at_unix_ns),
        "final_decision": _final_decision_from_verdict(msg),
        "total_execution_time_us": _total_execution_time_us(msg),
        "signals": signals,
        "trace_json": trace_steps,
        "crypto_algorithm": crypto_algorithm,
        "crypto_signature_hex": sig_hex,
        "crypto_key_id": "",
        "raw_manifest_sha256": raw_digest,
    }
