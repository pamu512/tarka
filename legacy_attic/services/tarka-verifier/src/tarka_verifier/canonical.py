"""Wire trace leaf encoding — matches ``tarka_core::evidence::merkle`` / ``tarka.merkle_wire``."""

from __future__ import annotations

import hashlib

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest, ExecutionStep

# Mirrors ``crates/tarka-core/src/evidence/merkle.rs`` LEAF_SCHEMA.
_LEAF_SCHEMA: bytes = b"tarka.evidence.wire.v1/TraceMerkleRoot/leaf\x01"


def _append_len_prefixed_trace(buf: bytearray, data: bytes) -> None:
    if len(data) > 0xFFFF_FFFF:
        raise ValueError("encoded field length exceeds u32::MAX")
    buf.extend(len(data).to_bytes(4, "big"))
    buf.extend(data)


def wire_canonical_step_bytes(step: ExecutionStep) -> bytes:
    """Canonical bytes for one trace row (operand sort + snapshot key sort)."""
    out = bytearray()
    out.extend(step.sequence.to_bytes(4, "big"))
    _append_len_prefixed_trace(out, step.rule_id.encode("utf-8"))
    _append_len_prefixed_trace(out, step.operator.encode("utf-8"))

    operands = sorted(step.operands)
    if len(operands) > 0xFFFF_FFFF:
        raise ValueError("operand count exceeds u32::MAX")
    out.extend(len(operands).to_bytes(4, "big"))
    for op in operands:
        _append_len_prefixed_trace(out, op.encode("utf-8"))

    out.append(1 if step.result else 0)

    snap_keys = sorted(step.state_snapshot.keys())
    if len(snap_keys) > 0xFFFF_FFFF:
        raise ValueError("snapshot key count exceeds u32::MAX")
    out.extend(len(snap_keys).to_bytes(4, "big"))
    for k in snap_keys:
        v = step.state_snapshot.get(k)
        if v is None:
            raise ValueError("state_snapshot missing key after sort")
        _append_len_prefixed_trace(out, k.encode("utf-8"))
        _append_len_prefixed_trace(out, v.encode("utf-8"))

    return bytes(out)


def wire_leaf_digest(step: ExecutionStep) -> bytes:
    body = wire_canonical_step_bytes(step)
    hasher = hashlib.sha256()
    hasher.update(_LEAF_SCHEMA)
    hasher.update(body)
    return hasher.digest()


def wire_trace_leaf_digests(manifest: EvidenceManifest) -> list[bytes]:
    return [wire_leaf_digest(step) for step in manifest.trace]


def wire_trace_inner_root(leaf_digests: list[bytes]) -> bytes:
    """SHA-256 Merkle root over leaf digests; empty trace ⇒ 32 zero bytes (Rust contract)."""
    if not leaf_digests:
        return bytes(32)
    from tarka.merkle_wire import merkle_root_rs_sha256

    return merkle_root_rs_sha256(leaf_digests)
