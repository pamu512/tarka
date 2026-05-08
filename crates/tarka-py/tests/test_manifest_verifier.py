"""Tests for wire manifest hashing + Ed25519ph verification (libsodium / Rust semantics)."""

from __future__ import annotations

import nacl.bindings as sodium
import pytest

from tarka.evidence.v1 import evidence_pb2
from tarka.verifier import (
    ManifestVerifier,
    _calculate_trace_root,
    _hash_signals_map,
    _seal_super_block_digest,
)


def _wire_manifest_empty_trace(
    *,
    manifest_id: str = "mid-1",
    git_hash: str = "deadbeef",
) -> evidence_pb2.EvidenceManifest:
    m = evidence_pb2.EvidenceManifest()
    m.manifest_id = manifest_id
    m.engine.version = "0.1.0"
    m.engine.git_hash = git_hash
    return m


def test_verify_ok_signed_empty_signals_empty_trace() -> None:
    seed = b"\x05" * 32
    pk, sk = sodium.crypto_sign_seed_keypair(seed)

    m = _wire_manifest_empty_trace()
    signals_digest = _hash_signals_map(dict(m.signals))
    trace_digest = _calculate_trace_root(list(m.trace))
    root = _seal_super_block_digest(
        signals_digest, trace_digest, m.manifest_id, m.engine.git_hash
    )

    st = sodium.crypto_sign_ed25519ph_state()
    sodium.crypto_sign_ed25519ph_update(st, root)
    sig = sodium.crypto_sign_ed25519ph_final_create(st, sk)

    m.merkle_root = root
    m.signature = sig

    raw = m.SerializeToString()
    assert ManifestVerifier.verify_manifest_integrity(raw, bytes(pk)) is True


def test_tampered_trace_fails() -> None:
    seed = b"\x06" * 32
    pk, sk = sodium.crypto_sign_seed_keypair(seed)

    m = _wire_manifest_empty_trace()
    signals_digest = _hash_signals_map(dict(m.signals))
    trace_digest = _calculate_trace_root(list(m.trace))
    root = _seal_super_block_digest(
        signals_digest, trace_digest, m.manifest_id, m.engine.git_hash
    )

    st = sodium.crypto_sign_ed25519ph_state()
    sodium.crypto_sign_ed25519ph_update(st, root)
    sig = sodium.crypto_sign_ed25519ph_final_create(st, sk)

    m.merkle_root = root
    m.signature = sig

    m2 = evidence_pb2.EvidenceManifest()
    m2.ParseFromString(m.SerializeToString())
    step = m2.trace.add()
    step.sequence = 1
    step.rule_id = "r"
    step.operator = "OP"
    step.result = True

    assert ManifestVerifier.verify_manifest_integrity(m2.SerializeToString(), bytes(pk)) is False


def test_garbage_bytes_false() -> None:
    assert ManifestVerifier.verify_manifest_integrity(b"not-protobuf", b"\x00" * 32) is False


def test_missing_engine_false() -> None:
    m = evidence_pb2.EvidenceManifest()
    m.manifest_id = "x"
    m.merkle_root = b"\x00" * 32
    m.signature = b"\x00" * 64
    assert ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), b"\x00" * 32) is False


@pytest.mark.parametrize("bad_len", [0, 16, 31, 33])
def test_bad_merkle_root_len_false(bad_len: int) -> None:
    m = _wire_manifest_empty_trace()
    m.merkle_root = b"\xab" * bad_len
    m.signature = b"\x00" * 64
    assert ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), b"\x00" * 32) is False


def test_operand_sorting_independent_of_input_order() -> None:
    """Matches Rust ``operand_order_irrelevant_when_sorted_in_canonical_form``."""
    m = evidence_pb2.EvidenceManifest()
    m.manifest_id = "m1"
    m.engine.version = "1"
    m.engine.git_hash = "g1"

    s1 = m.trace.add()
    s1.sequence = 1
    s1.rule_id = "r"
    s1.operator = "OP"
    s1.operands.extend(["z", "a"])
    s1.result = True

    m2 = evidence_pb2.EvidenceManifest()
    m2.ParseFromString(m.SerializeToString())
    m2.trace[0].operands[:] = ["a", "z"]

    assert _calculate_trace_root(list(m.trace)) == _calculate_trace_root(list(m2.trace))
