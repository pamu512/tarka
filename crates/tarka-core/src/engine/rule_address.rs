//! Content-addressable rule sets: SHA-256 over raw rule bytes with mandatory verification on load.

use std::fmt;
use std::sync::Arc;

use dashmap::DashMap;
use serde_json::error::Error as JsonError;
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use thiserror::Error;

/// SHA-256 digest used as the immutable identifier for a rule definition (`rule_json` UTF-8 bytes).
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct RuleContentId(pub [u8; 32]);

impl RuleContentId {
    /// Parses a 64-character lowercase / uppercase hex-encoded SHA-256 digest.
    pub fn parse_hex(hex_str: &str) -> Result<Self, SecurityIntegrityViolation> {
        let trimmed = hex_str.trim();
        let bytes = hex::decode(trimmed).map_err(|source| {
            SecurityIntegrityViolation::InvalidContentIdHex { source }
        })?;
        if bytes.len() != 32 {
            return Err(SecurityIntegrityViolation::InvalidContentIdLength {
                expected: 32,
                actual: bytes.len(),
            });
        }
        let mut out = [0u8; 32];
        out.copy_from_slice(&bytes);
        Ok(Self(out))
    }

    /// Constructs the id from a raw digest (e.g. after local hashing).
    pub const fn from_digest(digest: [u8; 32]) -> Self {
        Self(digest)
    }

    #[inline]
    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    pub fn to_hex(&self) -> String {
        hex::encode(self.0)
    }
}

impl fmt::Debug for RuleContentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("RuleContentId(")?;
        f.write_str(&self.to_hex())?;
        f.write_str(")")
    }
}

impl fmt::Display for RuleContentId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_hex())
    }
}

/// Returns the content address (SHA-256) of the given **exact** byte sequence (typically UTF-8 `rule_json`).
pub fn rule_content_sha256(raw_rule_bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(raw_rule_bytes).into()
}

/// In-memory content-addressed store: keys are [`RuleContentId`], values are the raw bytes that hash to that id.
pub struct ContentAddressedRuleStore {
    entries: DashMap<[u8; 32], Arc<[u8]>>,
}

impl Default for ContentAddressedRuleStore {
    fn default() -> Self {
        Self::new()
    }
}

impl ContentAddressedRuleStore {
    pub fn new() -> Self {
        Self {
            entries: DashMap::new(),
        }
    }

    /// Inserts `raw` under `sha256(raw)`; returns the generated id. Replaces any previous entry for the same id.
    pub fn insert(&self, raw: Vec<u8>) -> RuleContentId {
        let id = RuleContentId::from_digest(rule_content_sha256(&raw));
        self.entries
            .insert(id.0, Arc::from(raw.into_boxed_slice()));
        id
    }

    /// Returns raw bytes for `id` if present (does not re-verify; use [`load_verified_raw`] for integrity).
    pub fn get_raw(&self, id: &RuleContentId) -> Option<Arc<[u8]>> {
        self.entries.get(&id.0).map(|e| e.clone())
    }

    /// Fetches bytes and enforces that `sha256(bytes) == id` before returning.
    pub fn load_verified_raw(&self, id: &RuleContentId) -> Result<Arc<[u8]>, SecurityIntegrityViolation> {
        let bytes = self.get_raw(id).ok_or_else(|| {
            SecurityIntegrityViolation::UnknownRuleContentId {
                requested_hex: id.to_hex(),
            }
        })?;
        verify_rule_content(&bytes, id)?;
        Ok(bytes)
    }
}

/// Recomputes SHA-256 of `raw_rule_bytes` and compares to `expected_id` in constant time.
/// On mismatch, logs a `SecurityIntegrityViolation` and returns an error (engine must not use the rule).
pub fn verify_rule_content(
    raw_rule_bytes: &[u8],
    expected_id: &RuleContentId,
) -> Result<(), SecurityIntegrityViolation> {
    let digest = rule_content_sha256(raw_rule_bytes);
    let computed = RuleContentId::from_digest(digest);
    if bool::from(expected_id.0.ct_eq(&digest)) {
        return Ok(());
    }
    let requested_hex = expected_id.to_hex();
    let computed_hex = computed.to_hex();
    tracing::warn!(
        target: "tarka.security",
        event = "SecurityIntegrityViolation",
        violation = "ContentHashMismatch",
        requested_content_id = %requested_hex,
        computed_content_id = %computed_hex,
        "engine refused to load rule: content hash does not match requested content id"
    );
    Err(SecurityIntegrityViolation::ContentHashMismatch {
        requested_hex,
        computed_hex,
    })
}

/// Parses a hex content id, then runs [`verify_rule_content`].
pub fn verify_rule_content_hex(
    raw_rule_bytes: &[u8],
    requested_content_id_hex: &str,
) -> Result<RuleContentId, SecurityIntegrityViolation> {
    let expected = RuleContentId::parse_hex(requested_content_id_hex)?;
    verify_rule_content(raw_rule_bytes, &expected)?;
    Ok(expected)
}

/// Failures that block rule loading for security or format reasons.
#[derive(Debug, Error)]
pub enum SecurityIntegrityViolation {
    #[error(
        "SecurityIntegrityViolation::ContentHashMismatch: rule bytes hash to {computed_hex}, expected {requested_hex}"
    )]
    ContentHashMismatch {
        requested_hex: String,
        computed_hex: String,
    },
    #[error("SecurityIntegrityViolation::InvalidContentIdHex: {source}")]
    InvalidContentIdHex {
        #[source]
        source: hex::FromHexError,
    },
    #[error(
        "SecurityIntegrityViolation::InvalidContentIdLength: expected {expected} bytes, got {actual}"
    )]
    InvalidContentIdLength { expected: usize, actual: usize },
    #[error("SecurityIntegrityViolation::UnknownRuleContentId: no rule for content id {requested_hex}")]
    UnknownRuleContentId { requested_hex: String },
    #[error(transparent)]
    RuleJsonParse(#[from] JsonError),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_store_and_verify() {
        let raw = br#"{"kind":"compare_leaf","id":"x","path":"/a","op":"eq","expected":1}"#.to_vec();
        let store = ContentAddressedRuleStore::new();
        let id = store.insert(raw.clone());
        let got = store.load_verified_raw(&id).expect("load");
        assert_eq!(&*got, raw.as_slice());
    }

    #[test]
    fn mismatch_refuses_verify() {
        let raw = br#"{"kind":"compare_leaf","id":"x","path":"/a","op":"eq","expected":1}"#;
        let wrong_id = RuleContentId::from_digest([1u8; 32]);
        let err = verify_rule_content(raw, &wrong_id).expect_err("mismatch");
        assert!(matches!(err, SecurityIntegrityViolation::ContentHashMismatch { .. }));
    }

    #[test]
    fn parse_hex_round_trip() {
        let d = rule_content_sha256(b"abc");
        let id = RuleContentId::from_digest(d);
        let again = RuleContentId::parse_hex(&id.to_hex()).expect("parse");
        assert_eq!(id.0, again.0);
    }
}
