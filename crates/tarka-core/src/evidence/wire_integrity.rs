//! Wire [`crate::pb::EvidenceManifest`] integrity verification matching ``tarka.verifier.ManifestVerifier``
//! (Python) — independent auditor semantics.

use std::collections::HashMap;

use ed25519_dalek::{Signature, VerifyingKey};
use prost::Message;
use sha2::{Digest, Sha512};
use thiserror::Error;

use crate::evidence::hasher::hash_signals;
use crate::evidence::merkle::try_calculate_trace_root;
use crate::evidence::seal_super_block_digest;
use crate::pb::EvidenceManifest;

/// Stable failure codes aligned with Python ``VerificationFailureReason``.
#[derive(Debug, Error)]
pub enum WireManifestVerifyFailure {
    #[error("SIGNATURE_MISMATCH")]
    SignatureMismatch,
    #[error("ROOT_HASH_MISMATCH")]
    RootHashMismatch,
    #[error("DECODE_ERROR")]
    DecodeError,
    #[error("INCOMPLETE_PROOF")]
    IncompleteProof,
    #[error("ENGINE_METADATA_MISSING")]
    EngineMetadataMissing,
    #[error("INVALID_PUBLIC_KEY")]
    InvalidPublicKey,
    #[error("INVALID_SEAL_FIELDS")]
    InvalidSealFields,
    #[error("CANONICALIZATION_ERROR")]
    CanonicalizationError,
}

/// Verify raw protobuf bytes exactly like Python ``ManifestVerifier.verify_manifest_integrity``.
///
/// ``public_key`` must be the raw 32-byte Ed25519 verifying key.
pub fn verify_wire_manifest_integrity(
    manifest_bytes: &[u8],
    public_key: &[u8; 32],
) -> Result<(), WireManifestVerifyFailure> {
    let manifest = EvidenceManifest::decode(manifest_bytes).map_err(|_| {
        WireManifestVerifyFailure::DecodeError
    })?;

    let root_embedded = &manifest.merkle_root;
    let sig = &manifest.signature;

    if manifest.engine.is_none() {
        return Err(WireManifestVerifyFailure::EngineMetadataMissing);
    }
    let engine = manifest.engine.as_ref().expect("checked");

    let merkle_proof_missing = manifest.merkle_proof.is_none();

    if root_embedded.len() == 32 && sig.len() == 64 && merkle_proof_missing {
        return Err(WireManifestVerifyFailure::IncompleteProof);
    }

    if root_embedded.len() != 32 || sig.len() != 64 {
        return Err(WireManifestVerifyFailure::InvalidSealFields);
    }

    let vk = VerifyingKey::from_bytes(public_key).map_err(|_| {
        WireManifestVerifyFailure::InvalidPublicKey
    })?;

    let signals_map: HashMap<String, crate::pb::SignalValue> = manifest
        .signals
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();

    let signals_digest =
        hash_signals(&signals_map).map_err(|_| WireManifestVerifyFailure::CanonicalizationError)?;
    let trace_root =
        try_calculate_trace_root(&manifest.trace).map_err(|_| {
            WireManifestVerifyFailure::CanonicalizationError
        })?;

    if signals_digest.len() != 32 || trace_root.len() != 32 {
        return Err(WireManifestVerifyFailure::CanonicalizationError);
    }

    let recomputed = seal_super_block_digest(
        signals_digest.as_slice(),
        trace_root.as_slice(),
        manifest.manifest_id.as_str(),
        engine.git_hash.as_str(),
    )
    .map_err(|_| WireManifestVerifyFailure::CanonicalizationError)?;

    if recomputed.as_slice() != root_embedded.as_slice() {
        return Err(WireManifestVerifyFailure::RootHashMismatch);
    }

    let sig_obj =
        Signature::from_slice(sig.as_slice()).map_err(|_| WireManifestVerifyFailure::SignatureMismatch)?;

    let mut hasher = Sha512::new();
    hasher.update(recomputed.as_slice());
    vk.verify_prehashed(hasher, None, &sig_obj)
        .map_err(|_| WireManifestVerifyFailure::SignatureMismatch)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;

    #[test]
    fn golden_fixture_matches_python_parity() {
        let bytes = include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../tarka-py/tests/fixtures/golden_sealed_manifest.pb"
        ));
        let vk_hex = "8146640f02493af4fbc54fe33388e75dc2c937ae0b7727cc2b2afb1b75199a3e";
        let mut pk = [0u8; 32];
        hex::decode_to_slice(vk_hex, &mut pk).expect("hex");
        verify_wire_manifest_integrity(bytes, &pk).expect("golden manifest verifies");
    }

    #[test]
    fn wrong_key_fails_signature() {
        let bytes = include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../tarka-py/tests/fixtures/golden_sealed_manifest.pb"
        ));
        // Must be a *valid* Ed25519 public key; arbitrary 32 bytes can fail `VerifyingKey::from_bytes`
        // (`INVALID_PUBLIC_KEY`) and diverge from Python's path for a wrong-but-well-formed key.
        let other = SigningKey::from_bytes(&[7u8; 32]).verifying_key();
        let err = verify_wire_manifest_integrity(bytes, other.as_bytes()).unwrap_err();
        assert_eq!(err.to_string(), "SIGNATURE_MISMATCH");
    }

    #[test]
    fn signs_and_verifies_roundtrip() {
        let manifest = EvidenceManifest {
            manifest_id: "018f1234-5678-7abc-8def-123456789abc".into(),
            occurred_at_unix_ns: 17_000_000_000_000,
            engine: Some(crate::pb::EngineMetadata {
                version: "golden".into(),
                git_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
                environment: String::new(),
                engine_instance_id: String::new(),
            }),
            signals: Default::default(),
            trace: vec![],
            verdict: None,
            merkle_root: vec![],
            signature: vec![],
            merkle_proof: None,
        };

        let seed = [0x5Eu8; 32];
        let sk = SigningKey::from_bytes(&seed);
        let vk = sk.verifying_key();

        let mut tarka = crate::evidence::TarkaEvidence { manifest };
        tarka.seal(&sk).expect("seal");
        let proof = crate::evidence::merkle::try_generate_trace_merkle_proof(&tarka.manifest.trace)
            .expect("proof");
        tarka.manifest.merkle_proof = Some(proof);

        let wire = tarka.manifest;
        let mut buf = Vec::new();
        wire.encode(&mut buf).expect("encode");

        verify_wire_manifest_integrity(&buf, vk.as_bytes()).expect("verify own seal");
    }
}
