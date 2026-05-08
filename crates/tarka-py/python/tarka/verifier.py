"""Verify sealed wire ``EvidenceManifest`` integrity (Rust-aligned hashing + Ed25519ph)."""

from __future__ import annotations

import hashlib
import mmap
import os
import secrets
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Final, Optional, Union

import nacl.bindings as sodium
import nacl.exceptions as nacl_exc
from google.protobuf.message import DecodeError

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest, ExecutionStep, SignalValue
from tarka.merkle_wire import merkle_root_rs_sha256

# Mirrors ``crates/tarka-core/src/evidence/hasher.rs``
INPUT_STATE_SCHEMA: Final[bytes] = (
    b"tarka.evidence.wire.v1/DeterministicSignalHasher/input_state\x01"
)
# Mirrors ``crates/tarka-core/src/evidence/merkle.rs``
LEAF_SCHEMA: Final[bytes] = (
    b"tarka.evidence.wire.v1/TraceMerkleRoot/leaf\x01"
)
# Mirrors ``crates/tarka-core/src/evidence/mod.rs``
SEAL_SUPER_BLOCK_SCHEMA: Final[bytes] = (
    b"tarka.evidence.wire.v1/TarkaEvidence/seal_super_block\x01"
)

# Wire manifests larger than this use ``mmap`` when loaded from disk so the OS page cache backs the
# mapping instead of one contiguous ``bytes`` allocation on the Python heap (strictly ``>`` threshold).
_WIRE_MANIFEST_MMAP_THRESHOLD_BYTES: Final[int] = 10 * 1024 * 1024

# Buffer passed to ``EvidenceManifest.ParseFromString`` — typically ``bytes`` or read-only ``mmap``.
_WireManifestDecodeBuf = Union[bytes, mmap.mmap]

# Rust ``try_calculate_trace_root``: empty trace → 32 zero bytes for the trace intermediate in the
# seal super-block — **not** ``SHA256(EMPTY_TRACE_LEAF_DOMAIN)``. EMPTY_TRACE_LEAF_DOMAIN is the
# canonical wire namespace tag (legacy/internal crypto leaf synthesis only).
_EMPTY_TRACE_INTERMEDIATE: Final[bytes] = bytes(32)


class VerificationFailureReason(str, Enum):
    """Stable failure codes from :meth:`ManifestVerifier.verify_manifest_integrity`."""

    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
    ROOT_HASH_MISMATCH = "ROOT_HASH_MISMATCH"
    DECODE_ERROR = "DECODE_ERROR"
    INCOMPLETE_PROOF = "INCOMPLETE_PROOF"
    ENGINE_METADATA_MISSING = "ENGINE_METADATA_MISSING"
    INVALID_PUBLIC_KEY = "INVALID_PUBLIC_KEY"
    INVALID_SEAL_FIELDS = "INVALID_SEAL_FIELDS"
    CANONICALIZATION_ERROR = "CANONICALIZATION_ERROR"


class ManifestIntegrityError(RuntimeError):
    """
    Raised by Rust FFI (``tarka._tarka.evaluate``) when sealing / Merkle / signal hashing fails.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError`` handlers remain valid.
    ``failure_reason`` aligns with :class:`VerificationFailureReason` for structured handling across
    the Python/Rust boundary.
    """

    failure_reason: VerificationFailureReason

    def __init__(
        self,
        message: str,
        *,
        failure_reason: VerificationFailureReason,
    ) -> None:
        super().__init__(message)
        self.failure_reason = failure_reason


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of ``verify_manifest_integrity``."""

    status: bool
    failure_reason: Optional[VerificationFailureReason]

    def __bool__(self) -> bool:
        return self.status


def manifest_has_merkle_proof_field(manifest: EvidenceManifest) -> bool:
    """True iff the wire ``EvidenceManifest`` explicitly sets ``merkle_proof`` (proto3 ``optional``)."""
    return bool(manifest.HasField("merkle_proof"))


class ManifestVerifier:
    """Recomputes the sealed Merkle root and checks Ed25519ph like ``tarka_core::evidence::TarkaEvidence::seal``."""

    @staticmethod
    def verify_manifest_integrity_from_file(
        manifest_path: str | os.PathLike[str],
        public_key: bytes,
    ) -> VerificationResult:
        """
        Verify a manifest read from disk.

        For files strictly larger than 10 MiB, the protobuf payload is memory-mapped read-only
        before decoding so large blobs avoid an eager ``read()`` into the Python heap.
        """
        path = os.fspath(manifest_path)
        with open(path, "rb") as fh:
            if os.fstat(fh.fileno()).st_size > _WIRE_MANIFEST_MMAP_THRESHOLD_BYTES:
                with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    return ManifestVerifier.verify_manifest_integrity(mm, public_key)
            payload = fh.read()
        return ManifestVerifier.verify_manifest_integrity(payload, public_key)

    @staticmethod
    def verify_manifest_integrity(
        manifest_bytes: _WireManifestDecodeBuf,
        public_key: bytes,
    ) -> VerificationResult:
        """
        Verify wire manifest bytes against the sealed super-block and Ed25519ph signature.

        For manifests read from disk, prefer :meth:`verify_manifest_integrity_from_file` so inputs
        above 10 MiB can be memory-mapped instead of fully buffered in a single ``bytes`` object.

        ``public_key`` must be the raw 32-byte Ed25519 verifying key.

        Returns
        -------
        VerificationResult
            ``status`` is ``True`` only when decoding, Triple-DB proof presence, digests, and
            signature all succeed. ``failure_reason`` is ``None`` on success.
        """
        if len(public_key) != 32:
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.INVALID_PUBLIC_KEY,
            )

        try:
            manifest = EvidenceManifest()
            # Protobuf's Python decoder rejects ``mmap.mmap`` directly; ``memoryview`` is zero-copy
            # over ``bytes`` / ``mmap`` / ``bytearray`` and stays compatible if ``mmap.mmap`` is mocked.
            manifest.ParseFromString(memoryview(manifest_bytes))
        except DecodeError:
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.DECODE_ERROR,
            )

        root_embedded = manifest.merkle_root
        sig = manifest.signature

        # Proto3 submessages are never ``None`` on the Python API; use explicit field presence.
        if not manifest.HasField("engine"):
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.ENGINE_METADATA_MISSING,
            )

        engine = manifest.engine

        if (
            len(root_embedded) == 32
            and len(sig) == 64
            and not manifest_has_merkle_proof_field(manifest)
        ):
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.INCOMPLETE_PROOF,
            )

        if len(root_embedded) != 32 or len(sig) != 64:
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.INVALID_SEAL_FIELDS,
            )

        try:
            signals_digest = _hash_signals_map(dict(manifest.signals))
            trace_digest = _calculate_trace_root(list(manifest.trace))
            recomputed = _seal_super_block_digest(
                signals_digest,
                trace_digest,
                manifest.manifest_id,
                engine.git_hash,
            )
        except (_SignalHashError, _TraceMerkleError, _SealEncodeError):
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.CANONICALIZATION_ERROR,
            )

        if not secrets.compare_digest(recomputed, root_embedded):
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.ROOT_HASH_MISMATCH,
            )

        try:
            _verify_ed25519ph_prehashed_root(public_key, sig, recomputed)
        except _SignatureVerificationError:
            return VerificationResult(
                status=False,
                failure_reason=VerificationFailureReason.SIGNATURE_MISMATCH,
            )

        return VerificationResult(status=True, failure_reason=None)


class _SignalHashError(Exception):
    """Canonical signal hashing failed (unset payload, oversized field)."""


class _TraceMerkleError(Exception):
    """Trace leaf or Merkle construction failed."""


class _SealEncodeError(Exception):
    """Seal super-block preimage exceeded ``u32::MAX`` for a length prefix."""


class _SignatureVerificationError(Exception):
    """Ed25519ph verification failed."""


def _write_len_prefixed(buf: bytearray, chunk: bytes) -> None:
    if len(chunk) > 0xFFFF_FFFF:
        raise _SealEncodeError("length exceeds u32::MAX")
    buf.extend(len(chunk).to_bytes(4, "big"))
    buf.extend(chunk)


def _write_len_prefixed_digest(hasher, chunk: bytes) -> None:
    if len(chunk) > 0xFFFF_FFFF:
        raise _SignalHashError("length exceeds u32::MAX")
    hasher.update(len(chunk).to_bytes(4, "big"))
    hasher.update(chunk)


def _hash_signals_map(signals: dict[str, SignalValue]) -> bytes:
    keys = sorted(signals.keys())
    hasher = hashlib.sha256()
    hasher.update(INPUT_STATE_SCHEMA)
    for name in keys:
        sv = signals.get(name)
        if sv is None:
            raise _SignalHashError("missing key after sort")
        _update_hasher_with_signal(hasher, name, sv)
    return hasher.digest()


def _update_hasher_with_signal(
    hasher,
    field_name: str,
    sv: SignalValue,
) -> None:
    _write_len_prefixed_digest(hasher, field_name.encode("utf-8"))
    _write_len_prefixed_digest(hasher, sv.source.encode("utf-8"))

    which = sv.WhichOneof("value")
    if which is None:
        raise _SignalHashError(f"unset payload for `{field_name}`")

    if which == "str_val":
        hasher.update(bytes([1]))
        _write_len_prefixed_digest(hasher, sv.str_val.encode("utf-8"))
    elif which == "num_val":
        hasher.update(bytes([2]))
        n = sv.num_val
        u64 = struct.unpack(">Q", struct.pack(">d", n))[0]
        hasher.update(u64.to_bytes(8, "big"))
    elif which == "bool_val":
        hasher.update(bytes([3]))
        hasher.update(bytes([1 if sv.bool_val else 0]))
    elif which == "raw_bytes":
        hasher.update(bytes([4]))
        _write_len_prefixed_digest(hasher, sv.raw_bytes)
    else:
        raise _SignalHashError(f"unknown oneof member `{which}`")


def _canonical_step_bytes(step: ExecutionStep) -> bytes:
    out = bytearray()
    out.extend(step.sequence.to_bytes(4, "big"))
    _append_len_prefixed_trace(out, step.rule_id.encode("utf-8"))
    _append_len_prefixed_trace(out, step.operator.encode("utf-8"))

    operands = sorted(step.operands)
    if len(operands) > 0xFFFF_FFFF:
        raise _TraceMerkleError("operand count exceeds u32::MAX")
    out.extend(len(operands).to_bytes(4, "big"))
    for op in operands:
        _append_len_prefixed_trace(out, op.encode("utf-8"))

    out.append(1 if step.result else 0)

    snap_keys = sorted(step.state_snapshot.keys())
    if len(snap_keys) > 0xFFFF_FFFF:
        raise _TraceMerkleError("snapshot key count exceeds u32::MAX")
    out.extend(len(snap_keys).to_bytes(4, "big"))
    for k in snap_keys:
        v = step.state_snapshot.get(k)
        if v is None:
            raise _TraceMerkleError("state_snapshot missing key after sort")
        _append_len_prefixed_trace(out, k.encode("utf-8"))
        _append_len_prefixed_trace(out, v.encode("utf-8"))

    return bytes(out)


def _append_len_prefixed_trace(buf: bytearray, data: bytes) -> None:
    if len(data) > 0xFFFF_FFFF:
        raise _TraceMerkleError("encoded field length exceeds u32::MAX")
    buf.extend(len(data).to_bytes(4, "big"))
    buf.extend(data)


def _leaf_digest(step: ExecutionStep) -> bytes:
    body = _canonical_step_bytes(step)
    hasher = hashlib.sha256()
    hasher.update(LEAF_SCHEMA)
    hasher.update(body)
    return hasher.digest()


def _calculate_trace_root(trace: list[ExecutionStep]) -> bytes:
    if not trace:
        return _EMPTY_TRACE_INTERMEDIATE
    leaves = [_leaf_digest(step) for step in trace]
    return merkle_root_rs_sha256(leaves)


def _seal_super_block_digest(
    signals_digest: bytes,
    trace_digest: bytes,
    manifest_id: str,
    git_hash: str,
) -> bytes:
    if len(signals_digest) != 32 or len(trace_digest) != 32:
        raise _SealEncodeError("digest length invariant")

    buf = bytearray()
    buf.extend(SEAL_SUPER_BLOCK_SCHEMA)
    buf.extend(signals_digest)
    buf.extend(trace_digest)
    _write_len_prefixed(buf, manifest_id.encode("utf-8"))
    _write_len_prefixed(buf, git_hash.encode("utf-8"))
    return hashlib.sha256(bytes(buf)).digest()


def _verify_ed25519ph_prehashed_root(
    public_key_32: bytes,
    signature_64: bytes,
    merkle_root_32: bytes,
) -> None:
    if len(public_key_32) != 32:
        raise _SignatureVerificationError("Ed25519 public key must be 32 bytes")
    if len(signature_64) != 64:
        raise _SignatureVerificationError("Ed25519 signature must be 64 bytes")
    if len(merkle_root_32) != 32:
        raise _SignatureVerificationError("Merkle root must be 32 bytes")

    state = sodium.crypto_sign_ed25519ph_state()
    sodium.crypto_sign_ed25519ph_update(state, merkle_root_32)
    try:
        sodium.crypto_sign_ed25519ph_final_verify(state, signature_64, public_key_32)
    except nacl_exc.BadSignatureError as exc:
        raise _SignatureVerificationError(
            "Ed25519ph signature verification failed for Merkle root"
        ) from exc
    except ValueError as exc:
        raise _SignatureVerificationError(str(exc)) from exc
