"""Cryptographic round-trip: wire seal + rs_merkle proof + Ed25519ph (aligned with ``tarka.verifier``)."""

from __future__ import annotations

import base64
import binascii

import nacl.bindings as sodium
import pytest
from starlette.testclient import TestClient
from tarka.evidence.wire.v1.evidence_pb2 import EvidenceManifest
from tarka.verifier import (
    _calculate_trace_root,
    _hash_signals_map,
    _seal_super_block_digest,
)

from tarka_verifier.settings import reset_settings_cache
from tarka_verifier.verify_pipeline import verify_evidence_bundle


@pytest.fixture(autouse=True)
def _reset_settings():
    reset_settings_cache()
    yield
    reset_settings_cache()


def _sample_signed_manifest(seed: bytes) -> tuple[EvidenceManifest, bytes]:
    pk, sk = sodium.crypto_sign_seed_keypair(seed)
    m = EvidenceManifest()
    m.manifest_id = "018f1234-5678-7abc-8def-123456789abc"
    m.occurred_at_unix_ns = 1
    m.engine.version = "test"
    m.engine.git_hash = "a" * 40

    step = m.trace.add()
    step.sequence = 0
    step.rule_id = "r1"
    step.operator = "EQ"
    step.operands.append("a")
    step.result = True
    step.state_snapshot["k"] = "v"

    sd = _hash_signals_map(dict(m.signals))
    td = _calculate_trace_root(list(m.trace))
    seal_root = _seal_super_block_digest(sd, td, m.manifest_id, m.engine.git_hash)

    st = sodium.crypto_sign_ed25519ph_state()
    sodium.crypto_sign_ed25519ph_update(st, seal_root)
    sig = sodium.crypto_sign_ed25519ph_final_create(st, sk)

    m.merkle_root = seal_root
    m.signature = sig
    m.merkle_proof = b""

    return m, bytes(pk)


def test_end_to_end_verify_pipeline() -> None:
    manifest, pk = _sample_signed_manifest(b"k" * 32)
    raw = manifest.SerializeToString()

    rep = verify_evidence_bundle(
        manifest_protobuf=raw,
        merkle_proof_bytes=b"",
        verifying_public_key=pk,
    )
    assert rep.ok, rep.details


def test_tampered_manifest_fails() -> None:
    manifest, pk = _sample_signed_manifest(b"z" * 32)
    raw = manifest.SerializeToString()

    m2 = EvidenceManifest()
    m2.ParseFromString(raw)
    m2.trace[0].result = not m2.trace[0].result

    rep = verify_evidence_bundle(
        manifest_protobuf=m2.SerializeToString(),
        merkle_proof_bytes=b"",
        verifying_public_key=pk,
    )
    assert not rep.ok
    assert rep.failure_codes


def test_http_verify_endpoint_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from tarka_verifier.app import create_app

    manifest, pk = _sample_signed_manifest(b"q" * 32)
    monkeypatch.setenv(
        "TARKA_VERIFIER_VERIFYING_KEY_HEX", binascii.hexlify(pk).decode()
    )
    reset_settings_cache()

    client = TestClient(create_app())
    body = {
        "manifest_protobuf_base64": base64.b64encode(
            manifest.SerializeToString()
        ).decode(),
        "merkle_proof_bytes_base64": base64.b64encode(b"").decode(),
    }
    r = client.post("/v1/verify", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True


def test_http_triggers_pagerduty_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from tarka_verifier.app import create_app

    manifest, pk = _sample_signed_manifest(b"w" * 32)
    monkeypatch.setenv(
        "TARKA_VERIFIER_VERIFYING_KEY_HEX", binascii.hexlify(pk).decode()
    )
    monkeypatch.setenv("TARKA_VERIFIER_PAGERDUTY_ROUTING_KEY", "test-routing-key")
    reset_settings_cache()

    bad = bytearray(manifest.SerializeToString())
    bad[-1] ^= 0x01

    captured: dict[str, int] = {}

    def fake_alert(*_a: object, **_kw: object) -> None:
        captured["calls"] = captured.get("calls", 0) + 1

    monkeypatch.setattr("tarka_verifier.app._pagerduty_alert_sync", fake_alert)

    client = TestClient(create_app())
    body = {
        "manifest_protobuf_base64": base64.b64encode(bytes(bad)).decode(),
        "merkle_proof_bytes_base64": base64.b64encode(b"").decode(),
    }
    r = client.post("/v1/verify", json=body)
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert captured.get("calls", 0) == 1
