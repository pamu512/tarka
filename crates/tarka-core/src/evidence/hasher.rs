//! Deterministic SHA-256 of the **input signal set** (wire [`crate::pb::SignalValue`] map).
//!
//! Keys are taken from a [`std::collections::HashMap`], copied into a [`Vec`], sorted
//! lexicographically (`String`’s [`Ord`]), then iterated in that order so insertion order never affects
//! the digest.

use std::collections::HashMap;

use crate::pb::signal_value::Value;
use crate::pb::SignalValue;
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Domain separator for the single digest over all signals (“Input State”).
const INPUT_STATE_SCHEMA: &[u8] = b"tarka.evidence.wire.v1/DeterministicSignalHasher/input_state\x01";

/// Namespace for deterministic signal hashing.
#[derive(Debug, Clone, Copy, Default)]
pub struct DeterministicSignalHasher;

/// Failures while canonicalizing signals (unset oneof, oversized fields).
#[derive(Debug, Error, PartialEq, Eq)]
pub enum SignalHashError {
    #[error("signal `{0}` has no payload variant (value is unset)")]
    UnsetPayload(String),
    #[error("encoded length exceeds u32::MAX")]
    TooLarge,
    #[error("hash map missing key after sort (internal invariant)")]
    KeyInvariant,
}

/// Returns the SHA-256 digest (**32 bytes**) of the canonical encoding of `signals`.
///
/// Encoding: sorted keys; for each key, length-prefixed field name, length-prefixed `source`, then
/// tagged scalar (`str_val`, `num_val`, `bool_val`, `raw_bytes`) identical in spirit to
/// [`crate::evidence::integrity`] signal bodies.
pub fn hash_signals(signals: &HashMap<String, SignalValue>) -> Result<Vec<u8>, SignalHashError> {
    DeterministicSignalHasher::hash_signals(signals)
}

impl DeterministicSignalHasher {
    /// See [`hash_signals`].
    pub fn hash_signals(signals: &HashMap<String, SignalValue>) -> Result<Vec<u8>, SignalHashError> {
        let mut keys: Vec<&String> = signals.keys().collect();
        keys.sort();

        let mut hasher = Sha256::new();
        hasher.update(INPUT_STATE_SCHEMA);

        for key in keys {
            let sv = signals.get(key).ok_or(SignalHashError::KeyInvariant)?;
            update_hasher_with_entry(&mut hasher, key.as_str(), sv)?;
        }

        Ok(hasher.finalize().to_vec())
    }
}

fn update_hasher_with_entry(
    hasher: &mut Sha256,
    field_name: &str,
    sv: &SignalValue,
) -> Result<(), SignalHashError> {
    write_len_prefixed_to_digest(hasher, field_name.as_bytes())?;
    write_len_prefixed_to_digest(hasher, sv.source.as_bytes())?;

    match &sv.value {
        None => Err(SignalHashError::UnsetPayload(field_name.to_string())),
        Some(Value::StrVal(s)) => {
            hasher.update([1u8]);
            write_len_prefixed_to_digest(hasher, s.as_bytes())
        }
        Some(Value::NumVal(n)) => {
            hasher.update([2u8]);
            hasher.update(n.to_bits().to_be_bytes());
            Ok(())
        }
        Some(Value::BoolVal(b)) => {
            hasher.update([3u8]);
            hasher.update([u8::from(*b)]);
            Ok(())
        }
        Some(Value::RawBytes(b)) => {
            hasher.update([4u8]);
            write_len_prefixed_to_digest(hasher, b)
        }
    }
}

fn write_len_prefixed_to_digest(hasher: &mut Sha256, bytes: &[u8]) -> Result<(), SignalHashError> {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .map_err(|_| SignalHashError::TooLarge)?;
    hasher.update(len_u32.to_be_bytes());
    hasher.update(bytes);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pb::signal_value::Value;

    fn signal_str(source: &str, s: &str) -> SignalValue {
        SignalValue {
            source: source.into(),
            value: Some(Value::StrVal(s.into())),
        }
    }

    fn signal_num(source: &str, n: f64) -> SignalValue {
        SignalValue {
            source: source.into(),
            value: Some(Value::NumVal(n)),
        }
    }

    #[test]
    fn hash_identical_for_different_hashmap_insertion_orders() {
        let mut a = HashMap::new();
        a.insert("zebra".into(), signal_str("src", "z"));
        a.insert("apple".into(), signal_num("m", 1.5));
        a.insert("mango".into(), SignalValue {
            source: "x".into(),
            value: Some(Value::BoolVal(true)),
        });

        let mut b = HashMap::new();
        b.insert("mango".into(), SignalValue {
            source: "x".into(),
            value: Some(Value::BoolVal(true)),
        });
        b.insert("zebra".into(), signal_str("src", "z"));
        b.insert("apple".into(), signal_num("m", 1.5));

        let mut c = HashMap::new();
        c.insert("apple".into(), signal_num("m", 1.5));
        c.insert("zebra".into(), signal_str("src", "z"));
        c.insert("mango".into(), SignalValue {
            source: "x".into(),
            value: Some(Value::BoolVal(true)),
        });

        let ha = hash_signals(&a).expect("a");
        let hb = hash_signals(&b).expect("b");
        let hc = hash_signals(&c).expect("c");

        assert_eq!(ha.len(), 32);
        assert_eq!(ha, hb);
        assert_eq!(hb, hc);
    }

    #[test]
    fn raw_bytes_roundtrip_determinism() {
        let mut m1 = HashMap::new();
        m1.insert(
            "bin".into(),
            SignalValue {
                source: "".into(),
                value: Some(Value::RawBytes(vec![0, 255, 1])),
            },
        );

        let mut m2 = HashMap::new();
        m2.insert(
            "bin".into(),
            SignalValue {
                source: "".into(),
                value: Some(Value::RawBytes(vec![0, 255, 1])),
            },
        );

        assert_eq!(hash_signals(&m1).unwrap(), hash_signals(&m2).unwrap());
    }

    #[test]
    fn empty_map_is_stable() {
        let empty = HashMap::new();
        let h1 = hash_signals(&empty).expect("empty");
        let h2 = hash_signals(&empty).expect("empty");
        assert_eq!(h1.len(), 32);
        assert_eq!(h1, h2);
    }

    #[test]
    fn unset_payload_errors() {
        let mut m = HashMap::new();
        m.insert(
            "bad".into(),
            SignalValue {
                source: "".into(),
                value: None,
            },
        );
        assert_eq!(
            hash_signals(&m),
            Err(SignalHashError::UnsetPayload("bad".into()))
        );
    }

    #[test]
    fn different_keys_different_hash() {
        let mut m1 = HashMap::new();
        m1.insert("a".into(), signal_str("s", "v"));
        let mut m2 = HashMap::new();
        m2.insert("b".into(), signal_str("s", "v"));
        assert_ne!(hash_signals(&m1).unwrap(), hash_signals(&m2).unwrap());
    }
}
