//! Evidence manifest types generated from `proto/evidence.proto`.

include!(concat!(env!("OUT_DIR"), "/tarka.evidence.v1.rs"));

pub mod compact;
pub mod hasher;
pub mod integrity;
pub mod merkle;
pub mod wire_integrity;

use std::collections::{BTreeMap, HashMap};
use std::time::{SystemTime, UNIX_EPOCH};

use ed25519_dalek::{SignatureError, SigningKey};
use prost::Message;
use sha2::{Digest, Sha256, Sha512};
use thiserror::Error;
use uuid::Uuid;

/// Domain discriminator for the sealed super-block preimage (signals digest ‖ trace digest ‖ ids).
const SEAL_SUPER_BLOCK_SCHEMA: &[u8] = b"tarka.evidence.wire.v1/TarkaEvidence/seal_super_block\x01";

/// Hard failures while sealing a wire manifest ([`TarkaEvidence::seal`]). No cryptographic fields are
/// written on error.
#[derive(Debug, Error)]
pub enum EvidenceError {
    #[error(transparent)]
    SignalHash(#[from] crate::evidence::hasher::SignalHashError),
    #[error(transparent)]
    TraceMerkle(#[from] crate::evidence::merkle::TraceMerkleError),
    #[error("wire manifest requires engine metadata to seal")]
    MissingEngine,
    #[error("expected 32-byte intermediate digests from signal/trace hashing")]
    DigestLength,
    #[error("encoded field exceeds u32::MAX")]
    TooLarge,
    #[error(transparent)]
    Signature(#[from] SignatureError),
}

/// Scalar payloads mapped into wire [`crate::pb::SignalValue`] (see `tarka.evidence.wire.v1`).
#[derive(Clone, Debug, PartialEq)]
pub enum WireSignalScalar {
    Str(String),
    F64(f64),
    Bool(bool),
    Bytes(Vec<u8>),
}

impl From<String> for WireSignalScalar {
    fn from(s: String) -> Self {
        Self::Str(s)
    }
}

impl From<&str> for WireSignalScalar {
    fn from(s: &str) -> Self {
        Self::Str(s.to_owned())
    }
}

impl From<f64> for WireSignalScalar {
    fn from(n: f64) -> Self {
        Self::F64(n)
    }
}

impl From<f32> for WireSignalScalar {
    fn from(n: f32) -> Self {
        Self::F64(f64::from(n))
    }
}

impl From<bool> for WireSignalScalar {
    fn from(b: bool) -> Self {
        Self::Bool(b)
    }
}

impl From<Vec<u8>> for WireSignalScalar {
    fn from(b: Vec<u8>) -> Self {
        Self::Bytes(b)
    }
}

impl WireSignalScalar {
    fn into_pb_signal_value(self, source: String) -> crate::pb::SignalValue {
        use crate::pb::signal_value::Value;
        let value = Some(match self {
            Self::Str(s) => Value::StrVal(s),
            Self::F64(n) => Value::NumVal(n),
            Self::Bool(b) => Value::BoolVal(b),
            Self::Bytes(b) => Value::RawBytes(b),
        });
        crate::pb::SignalValue { source, value }
    }
}

/// Wire-format evidence envelope (`crate::pb::EvidenceManifest`) with helpers for building and serialization.
#[derive(Clone, Debug, PartialEq)]
pub struct TarkaEvidence {
    pub manifest: crate::pb::EvidenceManifest,
}

/// Returned when [`TarkaEvidence::validate_integrity`] finds missing cryptographic fields.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum TarkaEvidenceIntegrityError {
    #[error("merkle_root is not populated")]
    MerkleRootMissing,
    #[error("signature is not populated")]
    SignatureMissing,
}

fn unix_now_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| u64::try_from(d.as_nanos()).unwrap_or(u64::MAX))
        .unwrap_or(0)
}

impl TarkaEvidence {
    /// Builds a new manifest with a UUID v7 id, current wall-clock time, and engine metadata including
    /// this crate's version and [`env!("GIT_HASH")`] from the build script.
    pub fn new() -> Self {
        Self {
            manifest: crate::pb::EvidenceManifest {
                manifest_id: Uuid::now_v7().to_string(),
                occurred_at_unix_ns: unix_now_ns(),
                engine: Some(crate::pb::EngineMetadata {
                    version: env!("CARGO_PKG_VERSION").to_string(),
                    git_hash: env!("GIT_HASH").to_string(),
                    environment: String::new(),
                    engine_instance_id: String::new(),
                }),
                signals: BTreeMap::new(),
                trace: Vec::new(),
                verdict: None,
                merkle_root: Vec::new(),
                signature: Vec::new(),
                merkle_proof: None,
            },
        }
    }

    /// Inserts a signal under `name`, mapping `value` into the protobuf oneof and recording `source`.
    pub fn add_signal(
        &mut self,
        name: impl Into<String>,
        value: impl Into<WireSignalScalar>,
        source: impl Into<String>,
    ) {
        let key = name.into();
        let source_str = source.into();
        let sv = value.into().into_pb_signal_value(source_str);
        self.manifest.signals.insert(key, sv);
    }

    /// Appends a trace step (rule-engine DAG traversal record).
    pub fn add_step(&mut self, step: crate::pb::ExecutionStep) {
        self.manifest.trace.push(step);
    }

    /// Encodes the manifest with protobuf for wire transport or storage.
    pub fn to_bytes(&self) -> Vec<u8> {
        self.manifest.encode_to_vec()
    }

    /// JSON for UI or tooling (serde on generated types).
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(&self.manifest)
    }

    /// Ensures Merkle root and signature fields are present (non-empty) after signing.
    pub fn validate_integrity(&self) -> Result<(), TarkaEvidenceIntegrityError> {
        if self.manifest.merkle_root.is_empty() {
            return Err(TarkaEvidenceIntegrityError::MerkleRootMissing);
        }
        if self.manifest.signature.is_empty() {
            return Err(TarkaEvidenceIntegrityError::SignatureMissing);
        }
        Ok(())
    }

    /// Computes the signal hash ([`crate::evidence::hasher::hash_signals`]) and trace Merkle root
    /// ([`crate::evidence::merkle::try_calculate_trace_root`]), concatenates them with
    /// **`manifest_id`** and **`engine.git_hash`** into a super-block, SHA-256-hashes that blob as the
    /// manifest **`merkle_root`**, then signs that root with **Ed25519ph** ([`SigningKey::sign_prehashed`]
    /// / SHA-512 over the 32-byte root) matching verifier semantics elsewhere in this crate.
    ///
    /// On **any** error, **`merkle_root`** and **`signature`** are left unchanged (no partial seal).
    pub fn seal(&mut self, signing_key: &SigningKey) -> Result<(), EvidenceError> {
        let signals_map: HashMap<String, crate::pb::SignalValue> = self
            .manifest
            .signals
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

        let signals_hash = crate::evidence::hasher::hash_signals(&signals_map)?;
        let trace_root = crate::evidence::merkle::try_calculate_trace_root(&self.manifest.trace)?;

        if signals_hash.len() != 32 || trace_root.len() != 32 {
            return Err(EvidenceError::DigestLength);
        }

        let engine = self
            .manifest
            .engine
            .as_ref()
            .ok_or(EvidenceError::MissingEngine)?;

        let merkle_root_arr = seal_super_block_digest(
            signals_hash.as_slice(),
            trace_root.as_slice(),
            self.manifest.manifest_id.as_str(),
            engine.git_hash.as_str(),
        )?;

        let mut prehash = Sha512::new();
        prehash.update(merkle_root_arr.as_slice());
        let signature = signing_key.sign_prehashed(prehash, None)?;

        self.manifest.merkle_root = merkle_root_arr.to_vec();
        self.manifest.signature = signature.to_bytes().to_vec();
        Ok(())
    }
}

pub(crate) fn seal_super_block_digest(
    signals_digest: &[u8],
    trace_digest: &[u8],
    manifest_id: &str,
    git_hash: &str,
) -> Result<[u8; 32], EvidenceError> {
    if signals_digest.len() != 32 || trace_digest.len() != 32 {
        return Err(EvidenceError::DigestLength);
    }
    let mut buf = Vec::new();
    buf.extend_from_slice(SEAL_SUPER_BLOCK_SCHEMA);
    buf.extend_from_slice(signals_digest);
    buf.extend_from_slice(trace_digest);
    write_len_prefixed_seal(&mut buf, manifest_id.as_bytes())?;
    write_len_prefixed_seal(&mut buf, git_hash.as_bytes())?;
    Ok(Sha256::digest(&buf).into())
}

fn write_len_prefixed_seal(buf: &mut Vec<u8>, bytes: &[u8]) -> Result<(), EvidenceError> {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .map_err(|_| EvidenceError::TooLarge)?;
    buf.extend_from_slice(&len_u32.to_be_bytes());
    buf.extend_from_slice(bytes);
    Ok(())
}

impl Header {
    /// Interprets [`Header::manifest_id`] as a UUID (for example UUID v7 manifests).
    ///
    /// Returns `Err` when the slice length is not 16 octets.
    pub fn manifest_uuid(&self) -> Result<Uuid, uuid::Error> {
        Uuid::from_slice(&self.manifest_id)
    }
}

#[cfg(test)]
mod tests {
    use super::compact::EvidenceManifestCompact;
    use super::*;

    use ed25519_dalek::{Signature, SigningKey};
    use prost::Message;
    use sha2::{Digest, Sha512};
    use uuid::Uuid;

    #[test]
    fn serde_roundtrip_evidence_manifest() {
        let header = Header {
            manifest_id: Uuid::nil().as_bytes().to_vec(),
            engine_version: "deadbeef".into(),
            timestamp_ns: 42,
            engine_fingerprint: "fp-test".into(),
        };
        let mut entries = std::collections::BTreeMap::new();
        entries.insert(
            "score".into(),
            SignalValue {
                value: Some(signal_value::Value::DoubleValue(0.25)),
            },
        );
        let input_map = InputMap { entries };
        let trace = Trace {
            steps: vec![Step {
                rule_id: "r1".into(),
                logic_operator: "AND".into(),
                operands: vec!["a".into(), "b".into()],
                result: true,
                state_snapshot: std::collections::BTreeMap::from([(
                    "x".into(),
                    "1".into(),
                )]),
                otel_trace_id: String::new(),
            }],
        };
        let metadata = Metadata {
            final_decision: true,
            total_execution_time_us: 99,
        };
        let crypto_signature = CryptoSignature {
            algorithm: "ed25519".into(),
            signature: vec![1, 2, 3],
            key_id: "kid-1".into(),
        };
        let manifest = EvidenceManifest {
            header: Some(header),
            input_map: Some(input_map),
            trace: Some(trace),
            metadata: Some(metadata),
            crypto_signature: Some(crypto_signature),
        };

        let json = serde_json::to_string(&manifest).expect("serialize");
        let parsed: EvidenceManifest = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(manifest, parsed);
    }

    #[test]
    fn prost_roundtrip_binary() {
        let manifest = EvidenceManifest {
            header: Some(Header {
                manifest_id: Uuid::nil().as_bytes().to_vec(),
                engine_version: "abc".into(),
                timestamp_ns: 1,
                engine_fingerprint: String::new(),
            }),
            input_map: Some(InputMap {
                entries: std::collections::BTreeMap::from([(
                    "k".into(),
                    SignalValue {
                        value: Some(signal_value::Value::BoolValue(false)),
                    },
                )]),
            }),
            trace: None,
            metadata: None,
            crypto_signature: None,
        };
        let mut buf = Vec::new();
        manifest.encode(&mut buf).expect("encode");
        let decoded = EvidenceManifest::decode(buf.as_slice()).expect("decode");
        assert_eq!(manifest, decoded);
    }

    #[test]
    fn compact_manifest_roundtrip_through_generated_shape() {
        let manifest = EvidenceManifest {
            header: Some(Header {
                manifest_id: Uuid::nil().as_bytes().to_vec(),
                engine_version: "rev".into(),
                timestamp_ns: 7,
                engine_fingerprint: String::new(),
            }),
            input_map: None,
            trace: Some(Trace { steps: vec![] }),
            metadata: Some(Metadata {
                final_decision: false,
                total_execution_time_us: 3,
            }),
            crypto_signature: Some(CryptoSignature {
                algorithm: "test".into(),
                signature: vec![],
                key_id: "k".into(),
            }),
        };
        let compact: EvidenceManifestCompact =
            EvidenceManifestCompact::try_from(manifest.clone()).expect("compact");
        let restored: EvidenceManifest = compact.into();
        assert_eq!(manifest, restored);
    }

    #[test]
    fn tarka_evidence_new_sets_uuid_v7_manifest_and_git_metadata() {
        let ev = TarkaEvidence::new();
        let id = Uuid::parse_str(&ev.manifest.manifest_id).expect("manifest_id is UUID");
        assert_eq!(id.get_version(), Some(uuid::Version::SortRand));
        assert!(ev.manifest.occurred_at_unix_ns > 0);
        let engine = ev.manifest.engine.as_ref().expect("engine");
        assert_eq!(engine.version, env!("CARGO_PKG_VERSION"));
        assert!(!engine.git_hash.is_empty());
    }

    #[test]
    fn tarka_evidence_signals_steps_encode_json_roundtrip() {
        let mut ev = TarkaEvidence::new();
        ev.add_signal("score", 0.9_f64, "model-a");
        ev.add_signal("flag", true, "rules");
        ev.add_signal("note", "review", "manual");
        ev.add_signal("blob", vec![1_u8, 2, 3], "bytes-src");
        ev.add_step(crate::pb::ExecutionStep {
            sequence: 0,
            rule_id: "r1".into(),
            operator: "AND".into(),
            operands: vec!["a".into()],
            result: true,
            state_snapshot: BTreeMap::from([("k".into(), "v".into())]),
        });

        let score = ev.manifest.signals.get("score").expect("score");
        assert_eq!(
            score.value,
            Some(crate::pb::signal_value::Value::NumVal(0.9))
        );
        assert_eq!(score.source, "model-a");

        let bytes = ev.to_bytes();
        let decoded =
            crate::pb::EvidenceManifest::decode(bytes.as_slice()).expect("prost decode");
        assert_eq!(decoded, ev.manifest);

        let json = ev.to_json().expect("json");
        let parsed: crate::pb::EvidenceManifest = serde_json::from_str(&json).expect("serde");
        assert_eq!(parsed, ev.manifest);
    }

    #[test]
    fn tarka_evidence_validate_integrity_requires_root_and_signature() {
        let mut ev = TarkaEvidence::new();
        assert_eq!(
            ev.validate_integrity(),
            Err(TarkaEvidenceIntegrityError::MerkleRootMissing)
        );
        ev.manifest.merkle_root = vec![0_u8; 32];
        assert_eq!(
            ev.validate_integrity(),
            Err(TarkaEvidenceIntegrityError::SignatureMissing)
        );
        ev.manifest.signature = vec![1_u8; 64];
        assert!(ev.validate_integrity().is_ok());
    }

    #[test]
    fn tarka_evidence_seal_writes_root_and_ed25519ph_signature() {
        let mut ev = TarkaEvidence::new();
        ev.add_signal("risk", 0.42_f64, "features");
        let sk = SigningKey::from_bytes(&[21u8; 32]);
        ev.seal(&sk).expect("seal");
        ev.validate_integrity().expect("integrity after seal");

        let root: [u8; 32] = ev.manifest.merkle_root.as_slice().try_into().expect("root len");
        let mut prehash = Sha512::new();
        prehash.update(root.as_slice());
        let sig =
            Signature::from_slice(ev.manifest.signature.as_slice()).expect("signature length");
        sk.verifying_key()
            .verify_prehashed(prehash, None, &sig)
            .expect("Ed25519ph verify");
    }

    #[test]
    fn tarka_evidence_seal_missing_engine_leaves_crypto_clear() {
        let mut ev = TarkaEvidence::new();
        ev.manifest.engine = None;
        let sk = SigningKey::from_bytes(&[3u8; 32]);
        assert!(matches!(
            ev.seal(&sk),
            Err(EvidenceError::MissingEngine)
        ));
        assert!(ev.manifest.merkle_root.is_empty());
        assert!(ev.manifest.signature.is_empty());
    }

    #[test]
    fn tarka_evidence_seal_signal_hash_failure_leaves_crypto_clear() {
        let mut ev = TarkaEvidence::new();
        ev.manifest.signals.insert(
            "bad".into(),
            crate::pb::SignalValue {
                source: "".into(),
                value: None,
            },
        );
        let sk = SigningKey::from_bytes(&[4u8; 32]);
        assert!(matches!(
            ev.seal(&sk),
            Err(EvidenceError::SignalHash(_))
        ));
        assert!(ev.manifest.merkle_root.is_empty());
        assert!(ev.manifest.signature.is_empty());
    }
}
