"""Tests for wire manifest hashing + Ed25519ph verification (libsodium / Rust semantics)."""

from __future__ import annotations

from pathlib import Path

import nacl.bindings as sodium
import pytest

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest
from tarka.models import WireManifestDecodeError, decode_wire_manifest
from tarka.verifier import (
    ManifestVerifier,
    VerificationFailureReason,
    VerificationResult,
    _calculate_trace_root,
    _hash_signals_map,
    _seal_super_block_digest,
)


def _wire_manifest_empty_trace(
    *,
    manifest_id: str = "mid-1",
    git_hash: str = "deadbeef",
) -> EvidenceManifest:
    m = EvidenceManifest()
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
    m.merkle_proof = b""

    raw = m.SerializeToString()
    r = ManifestVerifier.verify_manifest_integrity(raw, bytes(pk))
    assert r.status is True
    assert r.failure_reason is None


def test_tampered_trace_fails_root_hash() -> None:
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
    m.merkle_proof = b""

    m2 = EvidenceManifest()
    m2.ParseFromString(m.SerializeToString())
    step = m2.trace.add()
    step.sequence = 1
    step.rule_id = "r"
    step.operator = "OP"
    step.result = True

    r = ManifestVerifier.verify_manifest_integrity(m2.SerializeToString(), bytes(pk))
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.ROOT_HASH_MISMATCH


def test_garbage_bytes_decode_error() -> None:
    r = ManifestVerifier.verify_manifest_integrity(b"not-protobuf", b"\x00" * 32)
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.DECODE_ERROR


def test_invalid_public_key() -> None:
    m = _wire_manifest_empty_trace()
    r = ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), b"short")
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.INVALID_PUBLIC_KEY


def test_decode_wire_manifest_raises_on_invalid() -> None:
    with pytest.raises(WireManifestDecodeError):
        decode_wire_manifest(b"not protobuf")


def test_decode_wire_manifest_roundtrip() -> None:
    m = _wire_manifest_empty_trace()
    raw = m.SerializeToString()
    got = decode_wire_manifest(raw)
    assert got.manifest_id == m.manifest_id


def test_missing_engine() -> None:
    m = EvidenceManifest()
    m.manifest_id = "x"
    m.merkle_root = b"\x00" * 32
    m.signature = b"\x00" * 64
    r = ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), b"\x00" * 32)
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.ENGINE_METADATA_MISSING


def test_missing_merkle_proof_incomplete() -> None:
    seed = b"\x07" * 32
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

    r = ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), bytes(pk))
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.INCOMPLETE_PROOF


@pytest.mark.parametrize("bad_len", [0, 16, 31, 33])
def test_bad_merkle_root_len_invalid_seal_fields(bad_len: int) -> None:
    m = _wire_manifest_empty_trace()
    m.merkle_root = b"\xab" * bad_len
    m.signature = b"\x00" * 64
    r = ManifestVerifier.verify_manifest_integrity(m.SerializeToString(), b"\x00" * 32)
    assert r.status is False
    assert r.failure_reason == VerificationFailureReason.INVALID_SEAL_FIELDS


def test_operand_sorting_independent_of_input_order() -> None:
    """Matches Rust ``operand_order_irrelevant_when_sorted_in_canonical_form``."""
    m = EvidenceManifest()
    m.manifest_id = "m1"
    m.engine.version = "1"
    m.engine.git_hash = "g1"

    s1 = m.trace.add()
    s1.sequence = 1
    s1.rule_id = "r"
    s1.operator = "OP"
    s1.operands.extend(["z", "a"])
    s1.result = True

    m2 = EvidenceManifest()
    m2.ParseFromString(m.SerializeToString())
    m2.trace[0].operands[:] = ["a", "z"]

    assert _calculate_trace_root(list(m.trace)) == _calculate_trace_root(list(m2.trace))


def test_verification_result_bool() -> None:
    assert bool(VerificationResult(status=True, failure_reason=None)) is True
    assert bool(VerificationResult(status=False, failure_reason=None)) is False


def test_verify_manifest_integrity_from_file_golden(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "golden_sealed_manifest.pb"
    vk_hex = "8146640f02493af4fbc54fe33388e75dc2c937ae0b7727cc2b2afb1b75199a3e"
    pk = bytes.fromhex(vk_hex)
    dst = tmp_path / "golden.pb"
    dst.write_bytes(fixture.read_bytes())

    r = ManifestVerifier.verify_manifest_integrity_from_file(dst, pk)
    assert r.status is True
    assert r.failure_reason is None


def test_mmap_load_matches_read_when_threshold_forced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With threshold 0, every non-empty file uses mmap; outcome matches in-memory verify."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "golden_sealed_manifest.pb"
    raw = fixture.read_bytes()
    vk_hex = "8146640f02493af4fbc54fe33388e75dc2c937ae0b7727cc2b2afb1b75199a3e"
    pk = bytes.fromhex(vk_hex)

    r_mem = ManifestVerifier.verify_manifest_integrity(raw, pk)

    monkeypatch.setattr(
        "tarka.verifier._WIRE_MANIFEST_MMAP_THRESHOLD_BYTES",
        0,
    )
    p = tmp_path / "g.pb"
    p.write_bytes(raw)
    r_mmap = ManifestVerifier.verify_manifest_integrity_from_file(p, pk)
    assert r_mmap == r_mem


def test_exactly_ten_mb_does_not_use_mmap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Strict ``> 10 MiB`` boundary: exactly threshold uses ``read()`` path."""
    size = 10 * 1024 * 1024  # keep in sync with ``tarka.verifier._WIRE_MANIFEST_MMAP_THRESHOLD_BYTES``
    # Deterministic pad so protobuf decode fails consistently for both paths.
    pad = tmp_path / "exact.bin"
    pad.write_bytes(b"\x00" * size)

    calls: list[str] = []

    real_mmap = __import__("mmap").mmap

    def tracing_mmap(fileno: int, length: int, *args: object, **kwargs: object) -> object:
        calls.append("mmap")
        return real_mmap(fileno, length, *args, **kwargs)

    monkeypatch.setattr("tarka.verifier.mmap.mmap", tracing_mmap)

    ManifestVerifier.verify_manifest_integrity_from_file(pad, b"\x00" * 32)
    assert calls == []
