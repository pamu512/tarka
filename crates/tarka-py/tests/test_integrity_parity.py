"""Rust ``tarka-core`` vs Python ``ManifestVerifier`` wire integrity parity.

The golden payload is produced by ``cargo run -p tarka-core --example gen_pytest_golden_manifest``.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import pytest

from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest
from tarka.verifier import (
    ManifestVerifier,
    _calculate_trace_root,
    _hash_signals_map,
    _seal_super_block_digest,
)

# From ``gen_pytest_golden_manifest`` stdout (must stay aligned with the fixture file).
_GOLDEN_MANIFEST_SHA256 = (
    "aa9f7ab7bbf15d231627fcd2a5781263fb3db6c99393637d0d1fcddb28d177ab"
)
_GOLDEN_MERKLE_ROOT_HEX = (
    "42da08cc492526ca6d84d28ffa4b9982792f44373a9bb15249c88205427bf4f2"
)
_GOLDEN_VERIFYING_KEY_HEX = (
    "8146640f02493af4fbc54fe33388e75dc2c937ae0b7727cc2b2afb1b75199a3e"
)


def _parity_violation(message: str) -> None:
    pytest.fail(f"Parity Violation: {message}")


def _golden_bytes() -> bytes:
    path = Path(__file__).resolve().parent / "fixtures" / "golden_sealed_manifest.pb"
    if not path.is_file():
        _parity_violation(f"missing golden fixture at {path}")
    return path.read_bytes()


def test_golden_manifest_matches_rust_sealed_output() -> None:
    raw = _golden_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if not secrets.compare_digest(observed, _GOLDEN_MANIFEST_SHA256):
        _parity_violation(
            f"golden byte fingerprint mismatch (expected {_GOLDEN_MANIFEST_SHA256}, got {observed}); "
            "regenerate with crates/tarka-core/examples/gen_pytest_golden_manifest.rs"
        )

    manifest = EvidenceManifest()
    manifest.ParseFromString(raw)

    embedded_hex = manifest.merkle_root.hex()
    if not secrets.compare_digest(embedded_hex, _GOLDEN_MERKLE_ROOT_HEX):
        _parity_violation(
            f"embedded Merkle root does not match Rust reference "
            f"(expected {_GOLDEN_MERKLE_ROOT_HEX}, got {embedded_hex})"
        )

    signals_digest = _hash_signals_map(dict(manifest.signals))
    trace_digest = _calculate_trace_root(list(manifest.trace))
    recomputed = _seal_super_block_digest(
        signals_digest,
        trace_digest,
        manifest.manifest_id,
        manifest.engine.git_hash,
    )
    if not secrets.compare_digest(recomputed, manifest.merkle_root):
        _parity_violation(
            "Python recomputed seal super-block digest differs from embedded manifest.merkle_root "
            f"(embedded={embedded_hex}, recomputed={recomputed.hex()})"
        )

    vk = bytes.fromhex(_GOLDEN_VERIFYING_KEY_HEX)
    if len(vk) != 32:
        _parity_violation("internal error: verifying key length")

    result = ManifestVerifier.verify_manifest_integrity(raw, vk)
    if not result.status:
        reason_s = result.failure_reason.value if result.failure_reason else "unknown"
        _parity_violation(
            f"ManifestVerifier rejected Rust-sealed golden manifest (failure_reason={reason_s})"
        )
