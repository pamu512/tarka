"""Wire-format ``EvidenceManifest`` (`tarka.evidence.wire.v1`) decode helpers."""

from __future__ import annotations

from google.protobuf.message import DecodeError

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest

WIRE_EVIDENCE_MANIFEST_FULL_NAME: str = EvidenceManifest.DESCRIPTOR.full_name


class WireManifestDecodeError(ValueError):
    """Raised when bytes are not a valid wire ``EvidenceManifest`` protobuf."""


def decode_wire_manifest(proto_bytes: bytes) -> EvidenceManifest:
    """Parse strict wire-schema bytes produced by ``encode_wire_manifest`` / PyO3 ``manifest_proto_bytes``."""
    msg = EvidenceManifest()
    try:
        msg.ParseFromString(proto_bytes)
    except DecodeError as exc:
        raise WireManifestDecodeError(
            "invalid wire EvidenceManifest protobuf (decode error)"
        ) from exc
    if msg.DESCRIPTOR.full_name != WIRE_EVIDENCE_MANIFEST_FULL_NAME:
        raise WireManifestDecodeError(
            f"unexpected message descriptor {msg.DESCRIPTOR.full_name!r}"
        )
    return msg
