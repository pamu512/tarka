//! Merkle root over wire-format [`crate::pb::ExecutionStep`] rows using **`rs_merkle`** + SHA-256.
//!
//! Leaf digests hash a domain-separated canonical encoding: **`sequence`**, **`rule_id`**,
//! **`operator`**, **`operands` sorted lexicographically**, **`result`**, and **`state_snapshot`**
//! entries sorted by key (same ordering guarantees as [`super::integrity`] except operands are
//! **sorted here** per trace-root contract).

use crate::pb::ExecutionStep;
use rs_merkle::algorithms::Sha256 as MerkleSha256;
use rs_merkle::{MerkleProof as RsMerkleProof, MerkleTree};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Inclusion proof over **all** trace leaves (indices `0..n`), same leaf digests as [`try_calculate_trace_root`].
pub type TraceMerkleProof = RsMerkleProof<MerkleSha256>;

/// Prepended to each step’s canonical bytes before SHA-256 so this leaf domain cannot collide with
/// unrelated preimage protocols.
const LEAF_SCHEMA: &[u8] = b"tarka.evidence.wire.v1/TraceMerkleRoot/leaf\x01";

/// Wire-format domain tag (`tarka.evidence.wire.v1`) shared with Python’s
/// ``tarka.evidence.wire.v1.EMPTY_TRACE_LEAF_DOMAIN``.
///
/// Used only by legacy/internal helpers that synthesize a single Merkle leaf when a manifest has no
/// trace rows (`crate::crypto::trace_leaf_digests`).
///
/// **`try_calculate_trace_root` / sealed manifests**: when the wire trace is empty, the trace
/// intermediate digest in the sealed super-block preimage is **32 zero bytes**, not
/// `SHA256(EMPTY_TRACE_LEAF_DOMAIN)`.
pub const EMPTY_TRACE_LEAF_DOMAIN: &[u8] = b"tarka.evidence.wire.v1/TRACE_EMPTY";

/// Generator namespace matching the trace Merkle construction.
#[derive(Debug, Clone, Copy, Default)]
pub struct TraceMerkleRoot;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum TraceMerkleError {
    #[error("encoded field length exceeds u32::MAX")]
    TooLarge,
    #[error("state_snapshot missing expected key during canonical encode")]
    SnapshotInvariant,
    #[error("internal Merkle tree has no root")]
    MerkleRootMissing,
}

/// Computes the SHA-256 Merkle root over `trace`, returning exactly **32 bytes**.
///
/// Returns **`vec![0u8; 32]`** when `trace` is empty (e.g. engine failure before any rule ran).
///
/// Operand strings are **sorted lexicographically** before hashing; `state_snapshot` keys are sorted.
/// Processing is iterative over steps and operands — suitable for large traces (10k+ steps) without
/// recursive stack growth in this layer (`rs_merkle` builds the tree iteratively).
///
/// Panics only if canonical encoding fails ([`TraceMerkleError::TooLarge`]) or the Merkle backend
/// returns no root; prefer [`try_calculate_trace_root`] for non-panicking control flow.
pub fn calculate_trace_root(trace: &[ExecutionStep]) -> Vec<u8> {
    try_calculate_trace_root(trace).expect("trace Merkle root (bounded fields)")
}

/// Fallible variant of [`calculate_trace_root`].
pub fn try_calculate_trace_root(trace: &[ExecutionStep]) -> Result<Vec<u8>, TraceMerkleError> {
    TraceMerkleRoot::try_calculate(trace)
}

impl TraceMerkleRoot {
    /// See [`calculate_trace_root`] (panicking).
    pub fn calculate(trace: &[ExecutionStep]) -> Vec<u8> {
        calculate_trace_root(trace)
    }

    /// See [`try_calculate_trace_root`].
    pub fn try_calculate(trace: &[ExecutionStep]) -> Result<Vec<u8>, TraceMerkleError> {
        if trace.is_empty() {
            return Ok(vec![0u8; 32]);
        }

        let mut leaves = Vec::with_capacity(trace.len());
        for step in trace {
            leaves.push(leaf_digest(step)?);
        }

        let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
        let root = tree.root().ok_or(TraceMerkleError::MerkleRootMissing)?;
        Ok(root.to_vec())
    }
}

/// Builds a Merkle inclusion proof over every trace step (`0..trace.len()`), serialized with
/// [`TraceMerkleProof::to_bytes`] (DirectHashesOrder).
///
/// Returns an **empty** `Vec` when `trace` is empty (no leaves; wire trace root is the zero digest).
pub fn try_generate_trace_merkle_proof(trace: &[ExecutionStep]) -> Result<Vec<u8>, TraceMerkleError> {
    if trace.is_empty() {
        return Ok(Vec::new());
    }
    let mut leaves = Vec::with_capacity(trace.len());
    for step in trace {
        leaves.push(leaf_digest(step)?);
    }
    let len = leaves.len();
    let tree = MerkleTree::<MerkleSha256>::from_leaves(&leaves);
    let indices: Vec<usize> = (0..len).collect();
    let proof = tree.proof(&indices);
    Ok(proof.to_bytes())
}

fn leaf_digest(step: &ExecutionStep) -> Result<[u8; 32], TraceMerkleError> {
    let body = canonical_step_bytes(step)?;
    let mut hasher = Sha256::new();
    hasher.update(LEAF_SCHEMA);
    hasher.update(&body);
    Ok(hasher.finalize().into())
}

/// Canonical encoding: sequence, ids, **sorted** operands, result, sorted snapshot (see module docs).
fn canonical_step_bytes(step: &ExecutionStep) -> Result<Vec<u8>, TraceMerkleError> {
    let mut out = Vec::new();
    out.extend_from_slice(&step.sequence.to_be_bytes());
    write_len_prefixed(&mut out, step.rule_id.as_bytes())?;
    write_len_prefixed(&mut out, step.operator.as_bytes())?;

    let mut operands: Vec<&str> = step.operands.iter().map(|s| s.as_str()).collect();
    operands.sort();

    let op_count: u32 = operands
        .len()
        .try_into()
        .map_err(|_| TraceMerkleError::TooLarge)?;
    out.extend_from_slice(&op_count.to_be_bytes());
    for op in operands {
        write_len_prefixed(&mut out, op.as_bytes())?;
    }

    out.push(if step.result { 1u8 } else { 0u8 });

    let mut snap_keys: Vec<&String> = step.state_snapshot.keys().collect();
    snap_keys.sort();

    let snap_count: u32 = snap_keys
        .len()
        .try_into()
        .map_err(|_| TraceMerkleError::TooLarge)?;
    out.extend_from_slice(&snap_count.to_be_bytes());
    for k in snap_keys {
        let v = step
            .state_snapshot
            .get(k)
            .ok_or(TraceMerkleError::SnapshotInvariant)?;
        write_len_prefixed(&mut out, k.as_bytes())?;
        write_len_prefixed(&mut out, v.as_bytes())?;
    }

    Ok(out)
}

fn write_len_prefixed(buf: &mut Vec<u8>, bytes: &[u8]) -> Result<(), TraceMerkleError> {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .map_err(|_| TraceMerkleError::TooLarge)?;
    buf.extend_from_slice(&len_u32.to_be_bytes());
    buf.extend_from_slice(bytes);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn empty_trace_yields_zero_root() {
        let root = calculate_trace_root(&[]);
        assert_eq!(root, vec![0u8; 32]);
    }

    #[test]
    fn operand_order_irrelevant_when_sorted_in_canonical_form() {
        let mk = |operands: Vec<String>| ExecutionStep {
            sequence: 1,
            rule_id: "r".into(),
            operator: "OP".into(),
            operands,
            result: true,
            state_snapshot: BTreeMap::new(),
        };

        let a = calculate_trace_root(&[mk(vec!["z".into(), "a".into()])]);
        let b = calculate_trace_root(&[mk(vec!["a".into(), "z".into()])]);
        assert_eq!(a, b);
        assert_eq!(a.len(), 32);
    }

    #[test]
    fn single_step_stable() {
        let step = ExecutionStep {
            sequence: 0,
            rule_id: "rule".into(),
            operator: "AND".into(),
            operands: vec!["x".into()],
            result: false,
            state_snapshot: BTreeMap::from([("k".into(), "v".into())]),
        };
        let r1 = calculate_trace_root(std::slice::from_ref(&step));
        let r2 = calculate_trace_root(std::slice::from_ref(&step));
        assert_eq!(r1, r2);
    }

    #[test]
    fn large_trace_no_stack_overflow_and_deterministic() {
        let mut trace = Vec::with_capacity(10_000);
        for i in 0u32..10_000 {
            trace.push(ExecutionStep {
                sequence: i,
                rule_id: format!("rule-{i}"),
                operator: "X".into(),
                operands: vec![format!("op-{i}")],
                result: i % 2 == 0,
                state_snapshot: BTreeMap::from([("s".into(), i.to_string())]),
            });
        }
        let r1 = calculate_trace_root(&trace);
        let r2 = calculate_trace_root(&trace);
        assert_eq!(r1.len(), 32);
        assert_eq!(r1, r2);
    }

    #[test]
    fn try_calculate_matches_calculate_trace_root() {
        let step = ExecutionStep {
            sequence: 7,
            rule_id: "id".into(),
            operator: "NOT".into(),
            operands: vec![],
            result: true,
            state_snapshot: BTreeMap::new(),
        };
        assert_eq!(
            calculate_trace_root(std::slice::from_ref(&step)),
            try_calculate_trace_root(std::slice::from_ref(&step)).unwrap()
        );
    }

    #[test]
    fn trace_merkle_proof_to_bytes_matches_tree_root() {
        let a = ExecutionStep {
            sequence: 0,
            rule_id: "r".into(),
            operator: "AND".into(),
            operands: vec!["a".into()],
            result: true,
            state_snapshot: BTreeMap::new(),
        };
        let b = ExecutionStep {
            sequence: 1,
            rule_id: "r2".into(),
            operator: "OR".into(),
            operands: vec!["b".into()],
            result: false,
            state_snapshot: BTreeMap::new(),
        };
        let trace = vec![a, b];
        let expected_root = try_calculate_trace_root(&trace).expect("root");
        let proof_bytes = try_generate_trace_merkle_proof(&trace).expect("proof");

        let tree = MerkleTree::<MerkleSha256>::from_leaves(
            &trace
                .iter()
                .map(|s| leaf_digest(s).unwrap())
                .collect::<Vec<_>>(),
        );
        let root = tree.root().expect("root");
        assert_eq!(root.to_vec(), expected_root);

        let proof = TraceMerkleProof::from_bytes(proof_bytes.as_slice()).expect("parse proof");
        let leaf_hashes: Vec<[u8; 32]> = trace.iter().map(|s| leaf_digest(s).unwrap()).collect();
        let indices: Vec<usize> = (0..trace.len()).collect();
        assert!(proof.verify(root, &indices, &leaf_hashes, trace.len()));
        assert_eq!(try_generate_trace_merkle_proof(&[]).unwrap(), Vec::<u8>::new());
    }
}
