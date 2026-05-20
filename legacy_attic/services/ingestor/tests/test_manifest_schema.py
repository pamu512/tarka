"""Schema registry validation for EvidenceManifest."""

from __future__ import annotations

import uuid

import pytest
from ingestor.manifest_row import ManifestDecodeError, decode_manifest_row, parse_evidence_manifest
from ingestor.manifest_schema import (
    EvidenceManifestJson,
    wire_payload_has_unknown_fields,
)
from ingestor.settings import IngestorSettings
from pydantic import ValidationError

from tarka.evidence.wire.v1 import evidence_pb2


def _minimal_manifest_bytes() -> bytes:
    m = evidence_pb2.EvidenceManifest()
    m.manifest_id = str(uuid.uuid4())
    m.occurred_at_unix_ns = 1
    m.engine.version = "test-engine"
    m.engine.git_hash = "abc123"
    sv = m.signals["risk_score"]
    sv.source = "unit_test"
    sv.num_val = 0.5
    m.verdict.action = "pass"
    m.verdict.latency_ns = 42_000
    return m.SerializeToString()


def test_decode_manifest_row_passes_registry() -> None:
    raw = _minimal_manifest_bytes()
    settings = IngestorSettings(manifest_schema_validation_enabled=True)
    row = decode_manifest_row(raw, settings=settings)
    assert row["tenant_id"] == "default"
    assert row["engine_version"] == "test-engine"
    assert row["final_decision"] == 1


def test_decode_manifest_row_respects_tenant_setting() -> None:
    raw = _minimal_manifest_bytes()
    settings = IngestorSettings(
        manifest_schema_validation_enabled=True,
        tenant_id="env-a",
    )
    row = decode_manifest_row(raw, settings=settings)
    assert row["tenant_id"] == "env-a"


def test_registry_disabled_skips_pydantic_projection_checks() -> None:
    raw = _minimal_manifest_bytes()
    settings = IngestorSettings(manifest_schema_validation_enabled=False)
    decode_manifest_row(raw, settings=settings)


def test_manifest_decode_error_not_schema_error() -> None:
    with pytest.raises(ManifestDecodeError):
        decode_manifest_row(b"not protobuf", settings=IngestorSettings())


def test_evidence_manifest_json_rejects_extra_keys() -> None:
    from google.protobuf.json_format import MessageToDict

    raw = _minimal_manifest_bytes()
    msg = parse_evidence_manifest(raw)
    d = MessageToDict(
        msg,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )
    d["phantom_field"] = True
    with pytest.raises(ValidationError):
        EvidenceManifestJson.model_validate(d)


def test_unknown_wire_fields_detection_false_for_current_encoder() -> None:
    raw = _minimal_manifest_bytes()
    msg = parse_evidence_manifest(raw)
    assert wire_payload_has_unknown_fields(msg) is False


def test_startup_pin_mismatch_raises() -> None:
    from ingestor.manifest_schema import assert_ingestor_descriptor_matches_pin

    bad = IngestorSettings(expected_manifest_descriptor_sha256="0" * 64)
    with pytest.raises(RuntimeError, match="does not match pinned digest"):
        assert_ingestor_descriptor_matches_pin(bad)


def test_startup_pin_matches_current_descriptor_set() -> None:
    from ingestor.descriptor_pin import (
        MANIFEST_DESCRIPTOR_SET_SHA256,
        manifest_descriptor_set_sha256,
    )
    from ingestor.manifest_schema import assert_ingestor_descriptor_matches_pin

    assert manifest_descriptor_set_sha256() == MANIFEST_DESCRIPTOR_SET_SHA256
    assert_ingestor_descriptor_matches_pin(IngestorSettings())
