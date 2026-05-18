//! Merkle anchoring and Ed25519 **prehashed** (Ed25519ph) signatures for [`EvidenceManifest`] trace integrity.
//!
//! ## Signing (production)
//! Preferred signing uses **AWS KMS** asymmetric keys (`ECC_NIST_EDWARDS25519`) via [`KmsSigner`]. The private key
//! never enters application memory; manifests are signed remotely with `ED25519_PH_SHA_512` + `RAW`
//! message type over the 32-byte Merkle root.
//!
//! Configure credentials and region using the standard AWS SDK chain (`AWS_PROFILE`, `AWS_REGION`,
//! instance role, etc.). Set **`TARKA_KMS_KEY_ID`** (or **`AWS_KMS_KEY_ID`**) to the CMK ID, ARN, or alias.
//!
//! ## Signing (local / air-gapped / small stacks)
//! When **`TARKA_SIGNING_KEY`** is set to a **hex-encoded 32-byte** Ed25519 seed, [`try_local_ed25519_ph_signer_from_env`]
//! returns [`LocalEd25519PhSigner`] so evaluation can anchor manifests **without KMS**. The seed is **secret** material
//! (equivalent to a private key); manage it with your secrets manager or e.g. Pulumi stack secrets — never commit it.
//!
//! ## Verification
//! Verifiers load an Ed25519 public key from **`TARKA_VERIFYING_KEY`** (hex-encoded 32-byte key).
//! Verification matches KMS signing: SHA-512 over the Merkle root, then Ed25519ph (`verify_prehashed`).

mod kms;

pub use kms::KmsSigner;

use std::env;
use std::future::Future;

use ed25519_dalek::{Signature, SignatureError, SigningKey, VerifyingKey};
use hex::FromHex;
use rs_merkle::algorithms::Sha256 as MerkleSha256;
use rs_merkle::{MerkleProof as RsMerkleProof, MerkleTree};
use sha2::{Digest, Sha256, Sha512};
use thiserror::Error;

use crate::evidence::EvidenceManifest;
use crate::evidence::merkle::EMPTY_TRACE_LEAF_DOMAIN;

/// Re-export for callers that want to name the Merkle hasher used by this module.
pub type MerkleHasher = MerkleSha256;

/// Inclusion proof (from `rs_merkle`) over trace leaves (see [`generate_proof`]).
pub type MerkleProof = RsMerkleProof<MerkleSha256>;

#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("environment variable `{name}` is not set")]
    EnvMissing { name: String },
    #[error("environment variable `{name}` is not valid hex: {source}")]
    EnvHex {
        name: String,
        #[source]
        source: hex::FromHexError,
    },
    #[error("environment variable `{name}` must decode to {expected} bytes, got {actual}")]
    EnvWrongLength {
        name: String,
        expected: usize,
        actual: usize,
    },
    #[error("Merkle tree has no root (internal error)")]
    MerkleRootMissing,
    #[error("invalid Ed25519 verifying key: {0}")]
    InvalidVerifyingKey(#[from] SignatureError),
}

#[derive(Debug, Error)]
pub enum VerifyError {
    #[error("Ed25519 signature verification failed")]
    SignatureInvalid,
    #[error(transparent)]
    Crypto(#[from] CryptoError),
}

/// Connectivity / configuration failures talking to AWS KMS (no private key material).
#[derive(Debug, Error)]
pub enum KmsConnectionError {
    #[error("TARKA_KMS_KEY_ID / AWS_KMS_KEY_ID is not set")]
    MissingKeyId,
    #[error("AWS configuration load failed: {0}")]
    ConfigLoad(String),
    #[error("network dispatch failure: {0}")]
    Dispatch(String),
    #[error("request timed out contacting KMS")]
    Timeout,
    #[error("HTTP error from KMS: {0}")]
    Http(String),
    #[error("KMS throttling ({code}): {msg}")]
    Throttling { code: String, msg: String },
    #[error("KMS service error ({code}): {msg}")]
    Service { code: String, msg: String },
    #[error("transient KMS error ({code}): {msg}")]
    SdkRetryable { code: String, msg: String },
    #[error("unexpected KMS response: {0}")]
    UnexpectedResponse(String),
    #[error("unexpected KMS client error: {0}")]
    Unexpected(String),
}

/// Failures while producing an Ed25519 signature for a Merkle root via KMS.
#[derive(Debug, Error)]
pub enum SigningError {
    #[error(transparent)]
    Kms(#[from] KmsConnectionError),
    #[error(
        "KMS returned signature bytes of invalid length (expected {expected}, got {actual})"
    )]
    InvalidSignatureLength { expected: usize, actual: usize },
    #[error("KMS signing failed after {attempts} attempts due to persistent throttling or overload")]
    ThrottlingExhausted { attempts: u32 },
    #[error(transparent)]
    SignatureFormat(#[from] SignatureError),
}

#[derive(Debug, Error)]
pub enum ProofSignError {
    #[error(transparent)]
    Crypto(#[from] CryptoError),
    #[error(transparent)]
    Signing(#[from] SigningError),
}

/// Async signer for 32-byte Merkle roots (Ed25519ph / KMS-compatible).
pub trait Signer: Send + Sync {
    fn sign_merkle_root<'a>(
        &'a self,
        root: &'a [u8; 32],
    ) -> impl Future<Output = Result<Signature, SigningError>> + Send + 'a;
}

/// In-process Ed25519ph signer (32-byte seed). Use only when **`TARKA_SIGNING_KEY`** is appropriate for your threat model.
#[derive(Debug, Clone)]
pub struct LocalEd25519PhSigner(pub SigningKey);

impl Signer for LocalEd25519PhSigner {
    fn sign_merkle_root<'a>(
        &'a self,
        root: &'a [u8; 32],
    ) -> impl Future<Output = Result<Signature, SigningError>> + Send + 'a {
        async move {
            let mut h = Sha512::new();
            h.update(root.as_slice());
            let sig = self
                .0
                .sign_prehashed(h, None)
                .map_err(SigningError::SignatureFormat)?;
            Ok(sig)
        }
    }
}

/// Loads a local signer from **`TARKA_SIGNING_KEY`** (64 hex chars = 32-byte Ed25519 seed).
///
/// Returns `Ok(None)` when the variable is unset or whitespace-only so callers can fall back to KMS.
pub fn try_local_ed25519_ph_signer_from_env() -> Result<Option<LocalEd25519PhSigner>, CryptoError> {
    let raw = match env::var("TARKA_SIGNING_KEY") {
        Ok(s) if !s.trim().is_empty() => s,
        Ok(_) | Err(_) => return Ok(None),
    };
    let bytes = decode_hex_key("TARKA_SIGNING_KEY", &raw)?;
    let sk = SigningKey::from_bytes(&bytes);
    Ok(Some(LocalEd25519PhSigner(sk)))
}

/// Loads verifying key from **`TARKA_VERIFYING_KEY`** (hex-encoded 32-byte Ed25519 public key).
pub fn verifying_key_from_env() -> Result<VerifyingKey, CryptoError> {
    let pk_hex = env::var("TARKA_VERIFYING_KEY").map_err(|_| CryptoError::EnvMissing {
        name: "TARKA_VERIFYING_KEY".into(),
    })?;
    let bytes = decode_hex_key("TARKA_VERIFYING_KEY", &pk_hex)?;
    VerifyingKey::from_bytes(&bytes).map_err(CryptoError::InvalidVerifyingKey)
}

fn decode_hex_key(name: &str, hex_str: &str) -> Result<[u8; 32], CryptoError> {
    let bytes = Vec::from_hex(hex_str.trim()).map_err(|source| CryptoError::EnvHex {
        name: name.to_string(),
        source,
    })?;
    if bytes.len() != 32 {
        return Err(CryptoError::EnvWrongLength {
            name: name.to_string(),
            expected: 32,
            actual: bytes.len(),
        });
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&bytes);
    Ok(out)
}

/// Deterministic encoding of a single trace [`crate::evidence::Step`] for Merkle leaves.
pub fn canonical_step_bytes(step: &crate::evidence::Step) -> Vec<u8> {
    let mut out = Vec::new();
    write_len_prefixed_bytes(&mut out, step.rule_id.as_bytes());
    write_len_prefixed_bytes(&mut out, step.logic_operator.as_bytes());
    let op_count: u32 = step
        .operands
        .len()
        .try_into()
        .expect("operand count fits u32 on supported targets");
    out.extend_from_slice(&op_count.to_be_bytes());
    for operand in &step.operands {
        write_len_prefixed_bytes(&mut out, operand.as_bytes());
    }
    out.push(u8::from(step.result));
    let scope_count: u32 = step
        .state_snapshot
        .len()
        .try_into()
        .expect("scope size fits u32 on supported targets");
    out.extend_from_slice(&scope_count.to_be_bytes());
    for (key, value) in &step.state_snapshot {
        write_len_prefixed_bytes(&mut out, key.as_bytes());
        write_len_prefixed_bytes(&mut out, value.as_bytes());
    }
    write_len_prefixed_bytes(&mut out, step.otel_trace_id.as_bytes());
    out
}

fn write_len_prefixed_bytes(buf: &mut Vec<u8>, bytes: &[u8]) {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .expect("bounded field length fits u32");
    buf.extend_from_slice(&len_u32.to_be_bytes());
    buf.extend_from_slice(bytes);
}

/// SHA-256 leaf digests for every [`EvidenceManifest`] trace step (deterministic order).
///
/// When there are no steps, returns a **single** digest `SHA256(EMPTY_TRACE_LEAF_DOMAIN)` so the
/// Merkle tree is non-degenerate. This differs from **wire** sealing
/// ([`crate::evidence::merkle::try_calculate_trace_root`]), which uses an all-zero trace digest when
/// the protobuf trace is empty.
pub fn trace_leaf_digests(manifest: &EvidenceManifest) -> Vec<[u8; 32]> {
    let steps = manifest
        .trace
        .as_ref()
        .map(|t| t.steps.as_slice())
        .unwrap_or_default();

    if steps.is_empty() {
        return vec![Sha256::digest(EMPTY_TRACE_LEAF_DOMAIN).into()];
    }

    steps
        .iter()
        .map(|step| Sha256::digest(canonical_step_bytes(step)).into())
        .collect()
}

/// Recomputes the Merkle root from the manifest trace (same construction as signing).
pub fn merkle_root(manifest: &EvidenceManifest) -> Result<[u8; 32], CryptoError> {
    let leaves = trace_leaf_digests(manifest);
    let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
    tree.root().ok_or(CryptoError::MerkleRootMissing)
}

/// Builds a Merkle inclusion proof over **all** trace leaves (indices `0..n`), using the same leaf
/// hashes as [`merkle_root`].
pub fn generate_proof(manifest: &EvidenceManifest) -> Result<MerkleProof, CryptoError> {
    let leaves = trace_leaf_digests(manifest);
    let len = leaves.len();
    let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
    let indices: Vec<usize> = (0..len).collect();
    Ok(tree.proof(&indices))
}

/// Proof over all leaves + Ed25519ph signature over the Merkle root (KMS-compatible).
pub async fn generate_proof_and_sign(
    signer: &impl Signer,
    manifest: &EvidenceManifest,
) -> Result<(MerkleProof, Signature), ProofSignError> {
    let proof = generate_proof(manifest)?;
    let root = merkle_root(manifest)?;
    let sig = signer.sign_merkle_root(&root).await?;
    Ok((proof, sig))
}

/// Verifies an Ed25519ph signature over SHA-512(Merkle root) using the verifying key from the environment.
pub fn verify_manifest(manifest: &EvidenceManifest, signature: &Signature) -> Result<(), VerifyError> {
    let vk = verifying_key_from_env()?;
    verify_manifest_with_key(manifest, signature, &vk)
}

/// Verifies Ed25519ph: SHA-512 over the 32-byte Merkle root, then verify with RFC 8032 prehash semantics.
pub fn verify_manifest_with_key(
    manifest: &EvidenceManifest,
    signature: &Signature,
    verifying_key: &VerifyingKey,
) -> Result<(), VerifyError> {
    let root = merkle_root(manifest).map_err(VerifyError::Crypto)?;
    let mut hasher = Sha512::new();
    hasher.update(root.as_slice());
    verifying_key
        .verify_prehashed(hasher, None, signature)
        .map_err(|_| VerifyError::SignatureInvalid)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::evidence::{Step, Trace};
    use ed25519_dalek::SigningKey;
    use std::sync::{Mutex, OnceLock};

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn with_verifying_env(pk_hex: &str, run: impl FnOnce() -> ()) {
        let _g = ENV_LOCK.lock().expect("env lock");
        env::set_var("TARKA_VERIFYING_KEY", pk_hex);
        run();
        env::remove_var("TARKA_VERIFYING_KEY");
    }

    fn sample_manifest() -> EvidenceManifest {
        EvidenceManifest {
            trace: Some(Trace {
                steps: vec![Step {
                    rule_id: "r1".into(),
                    logic_operator: "EQ".into(),
                    operands: vec!["a".into()],
                    result: true,
                    state_snapshot: [("k".into(), "v".into())].into_iter().collect(),
                    otel_trace_id: String::new(),
                }],
            }),
            ..empty_manifest()
        }
    }

    fn empty_manifest() -> EvidenceManifest {
        EvidenceManifest {
            header: None,
            input_map: None,
            trace: None,
            metadata: None,
            crypto_signature: None,
        }
    }

    fn test_seed_hex() -> &'static str {
        static SEED: OnceLock<String> = OnceLock::new();
        SEED.get_or_init(|| hex::encode([7u8; 32])).as_str()
    }

    #[test]
    fn try_local_ed25519_ph_signer_from_env_parses_hex_seed() {
        let _g = ENV_LOCK.lock().expect("env lock");
        let hex = test_seed_hex();
        env::set_var("TARKA_SIGNING_KEY", hex);
        let got = try_local_ed25519_ph_signer_from_env().expect("parse");
        assert!(got.is_some());
        env::remove_var("TARKA_SIGNING_KEY");
        assert!(try_local_ed25519_ph_signer_from_env().expect("ok").is_none());
    }

    #[test]
    fn merkle_root_stable_for_same_trace() {
        let m = sample_manifest();
        let a = merkle_root(&m).expect("root");
        let b = merkle_root(&m).expect("root");
        assert_eq!(a, b);
    }

    #[test]
    fn proof_roundtrip_rs_merkle() {
        let m = sample_manifest();
        let leaves = trace_leaf_digests(&m);
        let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
        let root = tree.root().expect("root");
        let proof = tree.proof(&(0..leaves.len()).collect::<Vec<_>>());
        assert!(proof.verify(
            root,
            &(0..leaves.len()).collect::<Vec<_>>(),
            &leaves,
            leaves.len()
        ));
    }

    #[tokio::test]
    async fn sign_and_verify_manifest_prehashed() {
        let seed = hex::decode(test_seed_hex()).expect("hex");
        let mut seed_arr = [0u8; 32];
        seed_arr.copy_from_slice(&seed);
        let sk = SigningKey::from_bytes(&seed_arr);
        let vk = sk.verifying_key();
        let pk_hex = hex::encode(vk.to_bytes());

        let signer = LocalEd25519PhSigner(sk);
        let manifest = sample_manifest();

        let (_proof, sig) = generate_proof_and_sign(&signer, &manifest)
            .await
            .expect("sign");

        with_verifying_env(&pk_hex, || {
            verify_manifest(&manifest, &sig).expect("verify");
        });
    }

    #[tokio::test]
    async fn verify_rejects_tampered_step() {
        let seed = hex::decode(test_seed_hex()).expect("hex");
        let mut seed_arr = [0u8; 32];
        seed_arr.copy_from_slice(&seed);
        let sk = SigningKey::from_bytes(&seed_arr);
        let vk = sk.verifying_key();
        let pk_hex = hex::encode(vk.to_bytes());

        let signer = LocalEd25519PhSigner(sk);
        let mut manifest = sample_manifest();
        let (_proof, sig) = generate_proof_and_sign(&signer, &manifest)
            .await
            .expect("sign");

        let trace = manifest.trace.as_mut().expect("trace");
        if let Some(step) = trace.steps.first_mut() {
            step.result = !step.result;
        }

        with_verifying_env(&pk_hex, || {
            assert!(matches!(
                verify_manifest(&manifest, &sig),
                Err(VerifyError::SignatureInvalid)
            ));
        });
    }
}
