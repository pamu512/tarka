"""Schema registry validation: wire EvidenceManifest must match the deployed protobuf contract."""

from __future__ import annotations

from typing import Any, Self

from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ingestor.descriptor_pin import manifest_descriptor_set_sha256
from ingestor.settings import IngestorSettings

EXPECTED_MANIFEST_FULL_NAME = "tarka.evidence.wire.v1.EvidenceManifest"


class SchemaIncompatibilityError(ValueError):
    """Manifest is incompatible with this ingestor's Evidence protobuf schema (drift or newer wire)."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail or message


def assert_ingestor_descriptor_matches_pin(settings: IngestorSettings) -> None:
    """
    Fail closed at worker startup if the runtime protobuf descriptor set does not match config.

    Compares SHA-256 of the canonical ``FileDescriptorSet`` for ``EvidenceManifest`` (including
    transitive imports) against :attr:`IngestorSettings.expected_manifest_descriptor_sha256`.
    """
    expected = settings.expected_manifest_descriptor_sha256.strip().lower()
    if not expected:
        raise RuntimeError(
            "expected_manifest_descriptor_sha256 is unset; refusing startup without a pinned "
            "protobuf descriptor digest"
        )
    actual = manifest_descriptor_set_sha256()
    if actual != expected:
        raise RuntimeError(
            "ingestor EvidenceManifest protobuf descriptor set does not match pinned digest "
            "(redeploy with matching ``tarka`` / proto codegen or update the pin after a deliberate "
            "schema change): "
            f"expected_sha256={expected} actual_sha256={actual}"
        )


def wire_payload_has_unknown_fields(msg: Any) -> bool:
    """True if the parsed message retains unknown wire fields (typically newer producer schema)."""
    serialized_full = msg.SerializeToString()
    clone = msg.__class__()
    clone.CopyFrom(msg)
    clone.DiscardUnknownFields()
    return serialized_full != clone.SerializeToString()


class EngineMetadataWireJson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = ""
    git_hash: str = ""
    environment: str = ""
    engine_instance_id: str = ""


class SignalValueWireJson(BaseModel):
    """Protobuf ``SignalValue`` JSON projection — exactly one scalar branch."""

    model_config = ConfigDict(extra="forbid")

    source: str = ""
    str_val: str | None = None
    num_val: float | None = None
    bool_val: bool | None = None
    raw_bytes: str | None = None

    @model_validator(mode="after")
    def exactly_one_value_branch(self) -> Self:
        branches = (
            self.str_val,
            self.num_val,
            self.bool_val,
            self.raw_bytes,
        )
        set_count = sum(1 for v in branches if v is not None)
        if set_count != 1:
            raise ValueError(
                "SignalValue JSON must set exactly one of "
                "str_val|num_val|bool_val|raw_bytes"
            )
        return self


class ExecutionStepWireJson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = 0
    rule_id: str = ""
    operator: str = ""
    operands: list[str] = Field(default_factory=list)
    result: bool = False
    state_snapshot: dict[str, str] = Field(default_factory=dict)

    @field_validator("sequence", mode="before")
    @classmethod
    def _coerce_sequence(cls, v: object) -> object:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v


class VerdictWireJson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = ""
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    latency_ns: int = 0

    @field_validator("latency_ns", mode="before")
    @classmethod
    def _coerce_latency(cls, v: object) -> object:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v


class WireEvidenceManifestJson(BaseModel):
    """Strict JSON shape produced by ``MessageToDict`` for wire ``EvidenceManifest``."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    occurred_at_unix_ns: int = 0
    engine: EngineMetadataWireJson | None = None
    signals: dict[str, SignalValueWireJson] = Field(default_factory=dict)
    trace: list[ExecutionStepWireJson] = Field(default_factory=list)
    verdict: VerdictWireJson | None = None
    merkle_root: str = ""
    signature: str = ""
    merkle_proof: str | None = None

    @field_validator("occurred_at_unix_ns", mode="before")
    @classmethod
    def _coerce_occurred(cls, v: object) -> object:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v


def validate_manifest_against_registry(msg: Any, settings: IngestorSettings) -> None:
    """
    Validate parsed EvidenceManifest before ClickHouse:
      - message type / full name
      - no unknown wire fields (newer schema)
      - protobuf-to-JSON structural validation via Pydantic (forbid extras / drift)
    """
    if not settings.manifest_schema_validation_enabled:
        return

    if msg.DESCRIPTOR.full_name != EXPECTED_MANIFEST_FULL_NAME:
        raise SchemaIncompatibilityError(
            f"unexpected message type: {msg.DESCRIPTOR.full_name!r} (expected {EXPECTED_MANIFEST_FULL_NAME!r})",
            detail="wrong_descriptor",
        )

    if wire_payload_has_unknown_fields(msg):
        raise SchemaIncompatibilityError(
            "EvidenceManifest contains protobuf fields not recognized by this ingestor "
            "(upgrade ingestor or downgrade producer)",
            detail="unknown_wire_fields",
        )

    try:
        as_dict = MessageToDict(
            msg,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )
        WireEvidenceManifestJson.model_validate(as_dict)
    except ValidationError as e:
        raise SchemaIncompatibilityError(
            "EvidenceManifest JSON projection failed Pydantic schema validation "
            f"(proto drift vs ingestor): {e}",
            detail="json_schema_validation_failed",
        ) from e


EvidenceManifestJson = WireEvidenceManifestJson
