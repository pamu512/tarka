"""End-to-end wire EvidenceManifest verification (trace Merkle proof + sealed root + Ed25519ph)."""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest
from tarka.merkle_wire import merkle_proof_root
from tarka.verifier import ManifestVerifier, VerificationFailureReason

from tarka_verifier.canonical import wire_trace_inner_root, wire_trace_leaf_digests


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    merkle_root_hex: str | None
    failure_codes: tuple[str, ...]
    details: dict[str, Any]


def decode_hex_pubkey(raw: str) -> bytes:
    s = raw.strip()
    try:
        out = binascii.unhexlify(s)
    except binascii.Error as exc:
        raise ValueError(f"verifying key is not valid hex: {exc}") from exc
    if len(out) != 32:
        raise ValueError("verifying key must decode to 32 bytes (Ed25519 public key)")
    return out


def _failure_codes_from_verifier(reason: VerificationFailureReason | None) -> tuple[str, ...]:
    if reason is None:
        return ()
    return (reason.value,)


def verify_evidence_bundle(
    *,
    manifest_protobuf: bytes,
    merkle_proof_bytes: bytes,
    verifying_public_key: bytes,
    signature_override: bytes | None = None,
) -> VerificationReport:
    """
    Verify wire ``EvidenceManifest``:

    1. ``ManifestVerifier`` — sealed super-block digest, ``merkle_root``, ``signature``, ``merkle_proof`` presence.
    2. rs_merkle inclusion proof bytes over trace leaves must reproduce the **trace inner** Merkle root.
    3. Request ``merkle_proof_bytes`` must match an embedded ``merkle_proof`` field when set.
    """
    detail: dict[str, Any] = {}
    failures: set[str] = set()

    try:
        manifest = EvidenceManifest()
        manifest.ParseFromString(manifest_protobuf)
    except DecodeError as exc:
        return VerificationReport(
            ok=False,
            merkle_root_hex=None,
            failure_codes=("MANIFEST_PARSE_ERROR",),
            details={"error": str(exc)},
        )

    to_verify = manifest_protobuf
    if signature_override is not None:
        if len(signature_override) != 64:
            return VerificationReport(
                ok=False,
                merkle_root_hex=None,
                failure_codes=("SIGNATURE_BYTES_INVALID",),
                details={"signature_byte_length": len(signature_override)},
            )
        altered = EvidenceManifest()
        altered.ParseFromString(manifest_protobuf)
        altered.signature = signature_override
        to_verify = altered.SerializeToString()

    sealed = ManifestVerifier.verify_manifest_integrity(to_verify, verifying_public_key)
    detail["manifest_integrity_status"] = sealed.status
    detail["manifest_integrity_reason"] = (
        sealed.failure_reason.value if sealed.failure_reason else None
    )
    if not sealed.status:
        failures.update(_failure_codes_from_verifier(sealed.failure_reason))

    leaves = wire_trace_leaf_digests(manifest)
    n = len(leaves)
    inner_root = wire_trace_inner_root(leaves)
    detail["trace_leaf_count"] = n
    detail["trace_inner_root_hex"] = inner_root.hex()

    proof_ok = False
    if n == 0:
        proof_ok = merkle_proof_bytes == b""
        if not proof_ok:
            detail["merkle_proof_error"] = "empty trace requires empty rs_merkle proof bytes"
    else:
        indices = list(range(n))
        try:
            from_proof = merkle_proof_root(merkle_proof_bytes, indices, leaves, n)
            proof_ok = from_proof == inner_root
            detail["merkle_proof_recomputed_hex"] = from_proof.hex()
        except (ValueError, RuntimeError) as exc:
            detail["merkle_proof_error"] = str(exc)

    detail["merkle_proof_valid"] = proof_ok
    if not proof_ok:
        failures.add("MERKLE_PROOF_INVALID")

    if manifest.HasField("merkle_proof"):
        embedded = bytes(manifest.merkle_proof)
        detail["merkle_proof_embedded_len"] = len(embedded)
        if embedded != merkle_proof_bytes:
            failures.add("MERKLE_PROOF_EMBEDDED_MISMATCH")
            detail["merkle_proof_embedded_mismatch"] = True

    ok = bool(
        sealed.status
        and proof_ok
        and "MERKLE_PROOF_EMBEDDED_MISMATCH" not in failures
    )

    merkle_hex = None
    if manifest.merkle_root and len(manifest.merkle_root) == 32:
        merkle_hex = manifest.merkle_root.hex()
    detail["sealed_merkle_root_hex"] = merkle_hex

    return VerificationReport(
        ok=ok,
        merkle_root_hex=merkle_hex,
        failure_codes=tuple(sorted(failures)),
        details=detail,
    )
