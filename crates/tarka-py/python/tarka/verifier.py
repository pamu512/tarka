"""Verify sealed wire ``EvidenceManifest`` integrity (Rust-aligned hashing + Ed25519ph)."""

from __future__ import annotations

import hashlib
import secrets
import struct
from typing import Final

import nacl.bindings as sodium
import nacl.exceptions as nacl_exc
from google.protobuf.message import DecodeError

from tarka.evidence.v1 import evidence_pb2
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

_ZERO32: Final[bytes] = bytes(32)


class ManifestVerifier:
    """Recomputes the sealed Merkle root and checks Ed25519ph like ``tarka_core::evidence::TarkaEvidence::seal``."""

    @staticmethod
    def verify_manifest_integrity(manifest_bytes: bytes, public_key: bytes) -> bool:
        """
        Return True iff the manifest decodes, intermediate digests match ``merkle_root``,
        and the detached signature verifies (Ed25519ph over SHA-512 of the 32-byte root).

        ``public_key`` must be the raw 32-byte Ed25519 verifying key.
        """
        try:
            manifest = evidence_pb2.EvidenceManifest()
            manifest.ParseFromString(manifest_bytes)
        except DecodeError:
            return False

        root_embedded = manifest.merkle_root
        sig = manifest.signature
        if len(root_embedded) != 32 or len(sig) != 64:
            return False

        engine = manifest.engine
        if engine is None:
            return False

        try:
            signals_digest = _hash_signals_map(manifest.signals)
            trace_digest = _calculate_trace_root(list(manifest.trace))
            recomputed = _seal_super_block_digest(
                signals_digest,
                trace_digest,
                manifest.manifest_id,
                engine.git_hash,
            )
        except (_SignalHashError, _TraceMerkleError, _SealEncodeError):
            return False

        if not secrets.compare_digest(recomputed, root_embedded):
            return False

        try:
            _verify_ed25519ph_prehashed_root(public_key, sig, recomputed)
        except _SignatureVerificationError:
            return False

        return True


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


def _hash_signals_map(signals: dict[str, evidence_pb2.SignalValue]) -> bytes:
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
    sv: evidence_pb2.SignalValue,
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


def _canonical_step_bytes(step: evidence_pb2.ExecutionStep) -> bytes:
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


def _leaf_digest(step: evidence_pb2.ExecutionStep) -> bytes:
    body = _canonical_step_bytes(step)
    hasher = hashlib.sha256()
    hasher.update(LEAF_SCHEMA)
    hasher.update(body)
    return hasher.digest()


def _calculate_trace_root(trace: list[evidence_pb2.ExecutionStep]) -> bytes:
    if not trace:
        return _ZERO32
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
