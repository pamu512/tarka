//! Evaluation **finalize** path: run the recursive evaluator, build the wire [`crate::pb::EvidenceManifest`],
//! optionally **seal** with [`KeyStore`] + [`crate::evidence::TarkaEvidence::seal`], and enforce auditability.
//!
//! Sealing runs **before** returning to FFI hosts (e.g. PyO3). When sealing is required (`fast_path == false`
//! and the outcome is a full manifest), an empty **signature** after seal triggers a **panic** so
//! unaudited successes cannot leave the engine.

use std::fs;
use std::path::{Path, PathBuf};

use ed25519_dalek::SigningKey;
use prost::Message;
use thiserror::Error;
use uuid::Uuid;

use super::evaluator::{EvaluateOutcome, Evaluator, ExternalDataSource, PartialManifest};
use crate::evidence::merkle::try_generate_trace_merkle_proof;
use crate::evidence::signal_value as legacy_sv;
use crate::evidence::{
    EvidenceManifest as LegacyManifest, SignalValue as LegacySignalValue, Step,
};
use crate::evidence::TarkaEvidence;
use crate::pb::signal_value::Value as WireValue;
use crate::pb::{
    EngineMetadata, EvidenceManifest as WireManifest, ExecutionStep, SignalValue as WireSignalValue,
    Verdict,
};
use serde_json::Value;

/// Secure access to the engine’s Ed25519 signing key (32-byte secret seed).
pub trait KeyStore: Send + Sync {
    /// Loads the [`SigningKey`] used for [`crate::evidence::TarkaEvidence::seal`].
    fn load_signing_key(&self) -> Result<SigningKey, KeyStoreError>;
}

/// Filesystem-backed key material for production (`/etc/tarka/keys/engine.priv` by default).
///
/// Accepted formats (after trimming ASCII whitespace):
/// - **64 hexadecimal characters** → 32-byte Ed25519 seed  
/// - **exactly 32 raw bytes** (non-UTF8-safe binary files supported)
#[derive(Clone, Debug)]
pub struct FileKeyStore {
    path: PathBuf,
}

impl FileKeyStore {
    /// Production path: `/etc/tarka/keys/engine.priv`.
    pub fn production_default() -> Self {
        Self {
            path: PathBuf::from("/etc/tarka/keys/engine.priv"),
        }
    }

    /// Uses **`TARKA_ENGINE_PRIVATE_KEY_PATH`** when set; otherwise [`Self::production_default`].
    pub fn from_env_or_default() -> Self {
        let path = std::env::var("TARKA_ENGINE_PRIVATE_KEY_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("/etc/tarka/keys/engine.priv"));
        Self { path }
    }

    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    fn read_seed_bytes(path: &Path) -> Result<[u8; 32], KeyStoreError> {
        let raw = fs::read(path).map_err(|source| KeyStoreError::Io {
            path: path.display().to_string(),
            source,
        })?;
        let body = raw
            .strip_prefix([0xef, 0xbb, 0xbf].as_slice())
            .unwrap_or(raw.as_slice());
        // Exact 32-byte files are interpreted as **raw** secrets — do not trim whitespace (0x09–0x0d
        // would otherwise vanish and yield an empty slice).
        if body.len() == 32 {
            let mut seed = [0u8; 32];
            seed.copy_from_slice(body);
            return Ok(seed);
        }
        let trimmed = body.trim_ascii_whitespace_bytes();
        let text = std::str::from_utf8(trimmed).map_err(|_| KeyStoreError::InvalidKeyFormat {
            reason: "engine private key must be 32 raw bytes or UTF-8 hex".into(),
        })?;
        let hex_s = text.trim();
        if hex_s.len() == 64 && hex_s.chars().all(|c| c.is_ascii_hexdigit()) {
            let bytes = hex::decode(hex_s)?;
            if bytes.len() != 32 {
                return Err(KeyStoreError::InvalidKeyFormat {
                    reason: format!("decoded hex length {} (expected 32)", bytes.len()),
                });
            }
            let mut seed = [0u8; 32];
            seed.copy_from_slice(&bytes);
            return Ok(seed);
        }
        Err(KeyStoreError::InvalidKeyFormat {
            reason: format!(
                "expected 32-byte secret or 64 hex chars, got {} bytes ({} after UTF-8 whitespace trim)",
                body.len(),
                trimmed.len()
            ),
        })
    }
}

trait TrimBytes {
    fn trim_ascii_whitespace_bytes(&self) -> &[u8];
}

impl TrimBytes for [u8] {
    fn trim_ascii_whitespace_bytes(&self) -> &[u8] {
        let mut start = 0;
        let mut end = self.len();
        while start < end && self[start].is_ascii_whitespace() {
            start += 1;
        }
        while end > start && self[end - 1].is_ascii_whitespace() {
            end -= 1;
        }
        &self[start..end]
    }
}

#[derive(Debug, Error)]
pub enum KeyStoreError {
    #[error("failed to read private key file `{path}`: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid engine private key: {reason}")]
    InvalidKeyFormat { reason: String },
    #[error(transparent)]
    HexDecode(#[from] hex::FromHexError),
}

impl KeyStore for FileKeyStore {
    fn load_signing_key(&self) -> Result<SigningKey, KeyStoreError> {
        let seed = Self::read_seed_bytes(&self.path)?;
        Ok(SigningKey::from_bytes(&seed))
    }
}

#[derive(Debug, Error)]
pub enum LegacyWireConvertError {
    #[error("legacy manifest missing header")]
    MissingHeader,
    #[error("manifest_id is not a valid UUID (expected 16 bytes)")]
    InvalidManifestId,
}

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error(transparent)]
    Convert(#[from] LegacyWireConvertError),
    #[error(transparent)]
    Seal(#[from] crate::evidence::EvidenceError),
    #[error(transparent)]
    KeyStore(#[from] KeyStoreError),
    #[error(transparent)]
    TraceMerkleProof(#[from] crate::evidence::merkle::TraceMerkleError),
    #[error("protobuf encode of wire manifest failed: {0}")]
    WireEncode(String),
}

/// Outcome after evaluation + optional wire seal (used by FFI).
pub struct FinalizedWireDecision {
    pub decision: bool,
    pub wire_manifest: WireManifest,
    pub legacy_manifest: LegacyManifest,
    pub partial_error: Option<String>,
    pub failing_rule_id: Option<String>,
    pub sealed: bool,
}

/// Runs [`Evaluator::evaluate`], maps the legacy manifest to the wire schema, sets [`Verdict`], then
/// — when `fast_path` is **false** and the evaluation produced a **full** manifest — loads a signing key
/// and calls [`TarkaEvidence::seal`].
///
/// # Panics
///
/// If sealing was performed successfully ([`EvidenceError`] not returned) but the wire manifest’s
/// **`signature`** is still empty, this function **panics** (`un-audited decision`).
pub fn finalize_decision_with_optional_seal<D: ExternalDataSource>(
    evaluator: &mut Evaluator<D>,
    data: &Value,
    fast_path: bool,
    key_store: &dyn KeyStore,
) -> Result<FinalizedWireDecision, RuntimeError> {
    let (decision, outcome): EvaluateOutcome = evaluator.evaluate(data);

    match outcome {
        Ok(legacy) => {
            let mut wire = legacy_manifest_to_wire(&legacy)?;
            set_verdict_from_legacy(&mut wire, &legacy);

            let sealed = if fast_path {
                false
            } else {
                let sk = key_store.load_signing_key()?;
                let mut tarka = TarkaEvidence {
                    manifest: std::mem::take(&mut wire),
                };
                tarka.seal(&sk)?;
                assert!(
                    !tarka.manifest.signature.is_empty(),
                    "un-audited decision: wire manifest signature empty after seal (engine audit invariant)"
                );
                wire = tarka.manifest;
                let proof = try_generate_trace_merkle_proof(&wire.trace)?;
                wire.merkle_proof = Some(proof);
                true
            };

            Ok(FinalizedWireDecision {
                decision,
                wire_manifest: wire,
                legacy_manifest: legacy,
                partial_error: None,
                failing_rule_id: None,
                sealed,
            })
        }
        Err(PartialManifest {
            evidence,
            failure_message,
            failing_rule_id,
        }) => {
            let wire = legacy_manifest_to_wire(&evidence)?;
            let mut w = wire;
            if let Some(meta) = evidence.metadata.as_ref() {
                w.verdict = Some(Verdict {
                    action: if meta.final_decision {
                        "partial_allow".into()
                    } else {
                        "partial_deny".into()
                    },
                    score: 0.0,
                    tags: vec!["partial_manifest".into()],
                    latency_ns: meta.total_execution_time_us.saturating_mul(1000),
                });
            }
            Ok(FinalizedWireDecision {
                decision: false,
                wire_manifest: w,
                legacy_manifest: evidence,
                partial_error: Some(failure_message),
                failing_rule_id,
                sealed: false,
            })
        }
    }
}

/// Encodes [`WireManifest`] for FFI transport.
pub fn encode_wire_manifest(m: &WireManifest) -> Result<Vec<u8>, RuntimeError> {
    let mut buf = Vec::new();
    m.encode(&mut buf)
        .map_err(|e| RuntimeError::WireEncode(e.to_string()))?;
    Ok(buf)
}

fn set_verdict_from_legacy(wire: &mut WireManifest, legacy: &LegacyManifest) {
    let meta = legacy.metadata.as_ref();
    let decision = meta.map(|m| m.final_decision).unwrap_or(false);
    let elapsed_us = meta.map(|m| m.total_execution_time_us).unwrap_or(0);
    wire.verdict = Some(Verdict {
        action: if decision {
            "pass".into()
        } else {
            "fail".into()
        },
        score: 0.0,
        tags: vec![],
        latency_ns: elapsed_us.saturating_mul(1000),
    });
}

fn legacy_manifest_to_wire(legacy: &LegacyManifest) -> Result<WireManifest, LegacyWireConvertError> {
    let header = legacy.header.as_ref().ok_or(LegacyWireConvertError::MissingHeader)?;
    let manifest_id = Uuid::from_slice(&header.manifest_id)
        .map_err(|_| LegacyWireConvertError::InvalidManifestId)?
        .to_string();

    let mut signals = std::collections::BTreeMap::new();
    if let Some(ref input) = legacy.input_map {
        for (k, v) in &input.entries {
            signals.insert(k.clone(), legacy_signal_to_wire(v));
        }
    }

    let mut trace_steps = Vec::new();
    if let Some(ref tr) = legacy.trace {
        for (idx, step) in tr.steps.iter().enumerate() {
            trace_steps.push(legacy_step_to_wire(idx as u32, step));
        }
    }

    let engine = Some(EngineMetadata {
        version: header.engine_version.clone(),
        git_hash: env!("GIT_HASH").to_string(),
        environment: String::new(),
        engine_instance_id: header.engine_fingerprint.clone(),
    });

    Ok(WireManifest {
        manifest_id,
        occurred_at_unix_ns: header.timestamp_ns,
        engine,
        signals,
        trace: trace_steps,
        verdict: None,
        merkle_root: Vec::new(),
        signature: Vec::new(),
        merkle_proof: None,
    })
}

fn legacy_signal_to_wire(s: &LegacySignalValue) -> WireSignalValue {
    let value = match &s.value {
        None => None,
        Some(legacy_sv::Value::BoolValue(b)) => Some(WireValue::BoolVal(*b)),
        Some(legacy_sv::Value::IntValue(i)) => Some(WireValue::NumVal(*i as f64)),
        Some(legacy_sv::Value::DoubleValue(d)) => Some(WireValue::NumVal(*d)),
        Some(legacy_sv::Value::StringValue(ref st)) => Some(WireValue::StrVal(st.clone())),
        Some(legacy_sv::Value::BytesValue(ref b)) => Some(WireValue::RawBytes(b.clone())),
    };
    WireSignalValue {
        source: String::new(),
        value,
    }
}

fn legacy_step_to_wire(sequence: u32, step: &Step) -> ExecutionStep {
    ExecutionStep {
        sequence,
        rule_id: step.rule_id.clone(),
        operator: step.logic_operator.clone(),
        operands: step.operands.clone(),
        result: step.result,
        state_snapshot: step.state_snapshot.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::evaluator::MockExternal;
    use crate::engine::trace::TraceContext;
    use crate::engine::{system_clock, RuleExpr};
    use std::io::Write;

    #[test]
    fn file_key_store_reads_hex_seed() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("engine.priv");
        let mut f = std::fs::File::create(&path).expect("create");
        writeln!(f, "  {}  ", hex::encode([5u8; 32])).expect("write");
        let ks = FileKeyStore::new(&path);
        let sk = ks.load_signing_key().expect("load");
        assert_eq!(sk.to_bytes(), [5u8; 32]);
    }

    #[test]
    fn finalize_fast_path_skips_seal_and_signature_empty_ok() {
        let rule = RuleExpr::And {
            id: "root".into(),
            children: vec![],
        };
        let mut eval = Evaluator::new(
            rule,
            TraceContext::with_clock_and_otel(system_clock(), None),
            MockExternal::default(),
            "test",
        );
        let ks = FileKeyStore::new("/nonexistent/should/not/read");
        let out = finalize_decision_with_optional_seal(&mut eval, &Value::Null, true, &ks)
            .expect("eval");
        assert!(!out.sealed);
        assert!(out.wire_manifest.signature.is_empty());
    }

    #[test]
    fn finalize_with_seal_populates_signature() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("engine.priv");
        std::fs::write(&path, [9u8; 32]).expect("write key");

        let rule = RuleExpr::And {
            id: "root".into(),
            children: vec![],
        };
        let mut eval = Evaluator::new(
            rule,
            TraceContext::with_clock_and_otel(system_clock(), None),
            MockExternal::default(),
            "test",
        );
        let ks = FileKeyStore::new(&path);
        let out = finalize_decision_with_optional_seal(&mut eval, &Value::Null, false, &ks)
            .expect("eval");
        assert!(out.sealed);
        assert!(!out.wire_manifest.signature.is_empty());
        assert!(!out.wire_manifest.merkle_root.is_empty());
        assert!(
            out.wire_manifest.merkle_proof.is_some(),
            "sealed wire manifest must carry trace Merkle inclusion proof (Triple-DB audit)"
        );
    }
}
