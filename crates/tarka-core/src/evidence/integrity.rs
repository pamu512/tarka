//! Deterministic SHA-256 Merkle root for wire-format [`crate::pb::EvidenceManifest`].
//!
//! Canonical encoding binds **`manifest_id`**, **signals** (keys sorted lexicographically; each
//! [`crate::pb::SignalValue`] includes sorted metadata where applicable), and **trace** steps in
//! list order. Each [`crate::pb::ExecutionStep`] becomes one Merkle leaf (SHA-256 of a canonical
//! byte sequence). A **prefix leaf** (manifest id + signals) is hashed first so the tree commits to
//! inputs before execution steps.
//!
//! Other manifest fields (`occurred_at_unix_ns`, `engine`, `verdict`, `merkle_root`, `signature`)
//! are intentionally excluded from this hash; they are bound separately (e.g. signing the root).
//!
//! Failures (oversized payloads, unset signal values) surface as [`ManifestHashError`] — no panics on
//! malformed or adversarial sizes.

use crate::pb::signal_value::Value;
use crate::pb::{EvidenceManifest, ExecutionStep, SignalValue};
use rs_merkle::algorithms::Sha256 as MerkleSha256;
use rs_merkle::MerkleTree;
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Schema discriminator prepended to the prefix blob so future encoding versions stay distinct.
const PREFIX_SCHEMA: &[u8] = b"tarka.evidence.wire.v1/ManifestHasher/prefix\x01";

/// Namespace for wire-manifest Merkle root calculation.
#[derive(Debug, Clone, Copy, Default)]
pub struct ManifestHasher;

/// Errors from canonical encoding or Merkle construction (never silent failure).
#[derive(Debug, Error, PartialEq, Eq)]
pub enum ManifestHashError {
    #[error("encoded length exceeds u32::MAX")]
    TooLarge,
    #[error("signal `{0}` has no payload variant (value is unset)")]
    SignalValueUnset(String),
    #[error("internal Merkle tree has no root")]
    MerkleRootMissing,
    #[error("signals map key disappeared during canonical encode")]
    SignalsMapInvariant,
    #[error("state_snapshot key disappeared during canonical encode")]
    SnapshotInvariant,
}

/// Computes the SHA-256 Merkle root over the prefix leaf (manifest id + lexicographically sorted
/// signals) and one leaf per [`crate::pb::ExecutionStep`] in trace order.
///
/// Returns exactly **32 bytes** (the tree root) on success.
pub fn calculate_root(manifest: &EvidenceManifest) -> Result<Vec<u8>, ManifestHashError> {
    ManifestHasher::calculate_root(manifest)
}

impl ManifestHasher {
    /// See [`calculate_root`].
    pub fn calculate_root(manifest: &EvidenceManifest) -> Result<Vec<u8>, ManifestHashError> {
        let mut leaves: Vec<[u8; 32]> = Vec::new();

        let prefix_bytes = canonical_prefix(manifest)?;
        leaves.push(hash_leaf(&prefix_bytes));

        for step in &manifest.trace {
            leaves.push(hash_leaf(&canonical_execution_step(step)?));
        }

        let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
        let root = tree.root().ok_or(ManifestHashError::MerkleRootMissing)?;
        Ok(root.to_vec())
    }
}

fn hash_leaf(canonical: &[u8]) -> [u8; 32] {
    Sha256::digest(canonical).into()
}

/// `manifest_id` UTF-8 plus signals sorted by key (explicit sort, independent of map representation).
fn canonical_prefix(manifest: &EvidenceManifest) -> Result<Vec<u8>, ManifestHashError> {
    let mut out = Vec::new();
    out.extend_from_slice(PREFIX_SCHEMA);
    write_len_prefixed_bytes(&mut out, manifest.manifest_id.as_bytes())?;

    let mut keys: Vec<&String> = manifest.signals.keys().collect();
    keys.sort();

    let n: u32 = keys.len().try_into().map_err(|_| ManifestHashError::TooLarge)?;
    out.extend_from_slice(&n.to_be_bytes());

    for key in keys {
        write_len_prefixed_bytes(&mut out, key.as_bytes())?;
        let sv = manifest
            .signals
            .get(key)
            .ok_or(ManifestHashError::SignalsMapInvariant)?;
        encode_signal_value(&mut out, sv, key)?;
    }

    Ok(out)
}

fn encode_signal_value(
    out: &mut Vec<u8>,
    sv: &SignalValue,
    key_for_errors: &str,
) -> Result<(), ManifestHashError> {
    write_len_prefixed_bytes(out, sv.source.as_bytes())?;

    match &sv.value {
        None => Err(ManifestHashError::SignalValueUnset(key_for_errors.to_string())),
        Some(Value::StrVal(s)) => {
            out.push(1u8);
            write_len_prefixed_bytes(out, s.as_bytes())?;
            Ok(())
        }
        Some(Value::NumVal(n)) => {
            out.push(2u8);
            out.extend_from_slice(&n.to_bits().to_be_bytes());
            Ok(())
        }
        Some(Value::BoolVal(b)) => {
            out.push(3u8);
            out.push(u8::from(*b));
            Ok(())
        }
        Some(Value::RawBytes(b)) => {
            out.push(4u8);
            write_len_prefixed_bytes(out, b)?;
            Ok(())
        }
    }
}

/// Canonical step encoding: operands in vector order; `state_snapshot` keys sorted lexicographically.
fn canonical_execution_step(step: &ExecutionStep) -> Result<Vec<u8>, ManifestHashError> {
    let mut out = Vec::new();
    out.extend_from_slice(&step.sequence.to_be_bytes());
    write_len_prefixed_bytes(&mut out, step.rule_id.as_bytes())?;
    write_len_prefixed_bytes(&mut out, step.operator.as_bytes())?;

    let op_count: u32 = step
        .operands
        .len()
        .try_into()
        .map_err(|_| ManifestHashError::TooLarge)?;
    out.extend_from_slice(&op_count.to_be_bytes());
    for op in &step.operands {
        write_len_prefixed_bytes(&mut out, op.as_bytes())?;
    }
    out.push(if step.result { 1u8 } else { 0u8 });

    let mut snap_keys: Vec<&String> = step.state_snapshot.keys().collect();
    snap_keys.sort();

    let snap_count: u32 = snap_keys
        .len()
        .try_into()
        .map_err(|_| ManifestHashError::TooLarge)?;
    out.extend_from_slice(&snap_count.to_be_bytes());
    for k in snap_keys {
        let v = step
            .state_snapshot
            .get(k)
            .ok_or(ManifestHashError::SnapshotInvariant)?;
        write_len_prefixed_bytes(&mut out, k.as_bytes())?;
        write_len_prefixed_bytes(&mut out, v.as_bytes())?;
    }

    Ok(out)
}

fn write_len_prefixed_bytes(buf: &mut Vec<u8>, bytes: &[u8]) -> Result<(), ManifestHashError> {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .map_err(|_| ManifestHashError::TooLarge)?;
    buf.extend_from_slice(&len_u32.to_be_bytes());
    buf.extend_from_slice(bytes);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pb::signal_value::Value;
    use crate::pb::{EngineMetadata, ExecutionStep, SignalValue};
    use std::collections::BTreeMap;

    fn sample_manifest() -> EvidenceManifest {
        EvidenceManifest {
            manifest_id: "550e8400-e29b-41d4-a716-446655440000".into(),
            occurred_at_unix_ns: 0,
            engine: None,
            signals: BTreeMap::new(),
            trace: vec![],
            verdict: None,
            merkle_root: vec![],
            signature: vec![],
            merkle_proof: None,
        }
    }

    #[test]
    fn calculate_root_is_deterministic() {
        let m = sample_manifest();
        let a = calculate_root(&m).expect("root a");
        let b = calculate_root(&m).expect("root b");
        assert_eq!(a, b);
        assert_eq!(a.len(), 32);
    }

    #[test]
    fn signal_key_order_is_irrelevant_for_determinism() {
        let mut m1 = sample_manifest();
        m1.signals.insert(
            "z".into(),
            SignalValue {
                source: "s".into(),
                value: Some(Value::StrVal("last".into())),
            },
        );
        m1.signals.insert(
            "a".into(),
            SignalValue {
                source: "s".into(),
                value: Some(Value::BoolVal(true)),
            },
        );

        let mut m2 = sample_manifest();
        m2.signals.insert(
            "a".into(),
            SignalValue {
                source: "s".into(),
                value: Some(Value::BoolVal(true)),
            },
        );
        m2.signals.insert(
            "z".into(),
            SignalValue {
                source: "s".into(),
                value: Some(Value::StrVal("last".into())),
            },
        );

        assert_eq!(
            calculate_root(&m1).expect("m1"),
            calculate_root(&m2).expect("m2")
        );
    }

    #[test]
    fn snapshot_key_sorting_is_deterministic() {
        let step = ExecutionStep {
            sequence: 1,
            rule_id: "r".into(),
            operator: "OP".into(),
            operands: vec![],
            result: false,
            state_snapshot: BTreeMap::from([
                ("b".into(), "2".into()),
                ("a".into(), "1".into()),
            ]),
        };
        let mut m1 = sample_manifest();
        m1.trace.push(step.clone());

        let mut step2 = step.clone();
        step2.state_snapshot = BTreeMap::new();
        step2.state_snapshot.insert("b".into(), "2".into());
        step2.state_snapshot.insert("a".into(), "1".into());
        let mut m2 = sample_manifest();
        m2.trace.push(step2);

        assert_eq!(
            calculate_root(&m1).expect("m1"),
            calculate_root(&m2).expect("m2")
        );
    }

    #[test]
    fn unset_signal_value_errors() {
        let mut m = sample_manifest();
        m.signals.insert(
            "x".into(),
            SignalValue {
                source: "".into(),
                value: None,
            },
        );
        assert_eq!(
            calculate_root(&m),
            Err(ManifestHashError::SignalValueUnset("x".into()))
        );
    }

    #[test]
    fn extra_manifest_fields_do_not_change_root() {
        let mut plain = sample_manifest();
        plain.signals.insert(
            "k".into(),
            SignalValue {
                source: "src".into(),
                value: Some(Value::NumVal(1.0)),
            },
        );

        let mut rich = plain.clone();
        rich.occurred_at_unix_ns = 99;
        rich.engine = Some(EngineMetadata {
            version: "v".into(),
            git_hash: "abc".into(),
            environment: "prod".into(),
            engine_instance_id: "i".into(),
        });

        assert_eq!(
            calculate_root(&plain).expect("plain"),
            calculate_root(&rich).expect("rich")
        );
    }

    #[test]
    fn trace_steps_change_root() {
        let mut m = sample_manifest();
        let r0 = calculate_root(&m).expect("empty trace");

        m.trace.push(ExecutionStep {
            sequence: 0,
            rule_id: "rule".into(),
            operator: "AND".into(),
            operands: vec![],
            result: true,
            state_snapshot: BTreeMap::new(),
        });
        let r1 = calculate_root(&m).expect("one step");
        assert_ne!(r0, r1);
    }
}
