//! Evidence-bundle verification (P1 proof-grade).
//!
//! Verifies the case-api compliance evidence bundle format offline:
//! canonical-JSON SHA-256 bundle hash, sequential record hash chain, and
//! HMAC-SHA256 bundle signature with key-id rotation awareness.
//!
//! Format (case_api/main.py:190-208):
//!   bundle_hash   = sha256(canonical_json(bundle_without_integrity_and_signature))
//!   hash_chain    = fold(records) sha256(f"{prev}:{canonical_json(record)}")
//!   signature     = hmac_sha256(key, canonical_json(bundle_without_signature))
//!   key_id        = sha256(key)[:12]

use serde_json::Value;

#[derive(Debug, thiserror::Error)]
pub enum VerifyError {
    #[error("bundle is not a JSON object")]
    NotAnObject,
    #[error("missing field: {0}")]
    MissingField(&'static str),
    #[error("integrity block missing or malformed")]
    BadIntegrity,
    #[error("bundle hash mismatch: expected {expected}, computed {computed}")]
    BundleHashMismatch { expected: String, computed: String },
    #[error("hash chain mismatch: expected {expected}, computed {computed}")]
    HashChainMismatch { expected: String, computed: String },
    #[error("signature mismatch: expected {expected}, computed {computed}")]
    SignatureMismatch { expected: String, computed: String },
    #[error("key id mismatch: bundle signed with {bundle}, provided key is {provided}")]
    KeyIdMismatch { bundle: String, provided: String },
}

/// Canonical JSON matching Python `json.dumps(sort_keys=True, separators=(",",":"))`.
fn canonical_json(value: &Value) -> String {
    // serde_json's BTreeMap-backed Value preserves insertion order; to match
    // Python's sort_keys we re-serialize with sorted keys recursively.
    fn sorted(v: &Value) -> Value {
        match v {
            Value::Object(map) => {
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                let mut out = serde_json::Map::new();
                for k in keys {
                    out.insert(k.clone(), sorted(&map[k]));
                }
                Value::Object(out)
            }
            Value::Array(items) => Value::Array(items.iter().map(sorted).collect()),
            other => other.clone(),
        }
    }
    serde_json::to_string(&sorted(value)).expect("value is valid JSON")
}

fn sha256_hex(data: &[u8]) -> String {
    use sha2::Digest;
    let mut h = sha2::Sha256::new();
    h.update(data);
    hex::encode(h.finalize())
}

fn hmac_sha256_hex(key: &[u8], data: &[u8]) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).expect("hmac accepts any key length");
    mac.update(data);
    hex::encode(mac.finalize().into_bytes())
}

/// Key id derivation: sha256(key)[:12]
pub fn key_id_for(key: &str) -> String {
    sha256_hex(key.as_bytes())[..12].to_string()
}

pub struct VerifyReport {
    pub bundle_hash_ok: bool,
    pub hash_chain_ok: bool,
    pub signature_ok: bool,
    pub key_id_ok: bool,
    pub key_id: String,
    pub records: usize,
}

impl std::fmt::Debug for VerifyReport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("VerifyReport")
            .field("bundle_hash_ok", &self.bundle_hash_ok)
            .field("hash_chain_ok", &self.hash_chain_ok)
            .field("signature_ok", &self.signature_ok)
            .field("key_id_ok", &self.key_id_ok)
            .field("key_id", &self.key_id)
            .field("records", &self.records)
            .finish()
    }
}

impl VerifyReport {
    pub fn ok(&self) -> bool {
        self.bundle_hash_ok && self.hash_chain_ok && self.signature_ok && self.key_id_ok
    }
}

/// Verify a bundle (as parsed JSON) against the signing key.
///
/// `key` is the raw signing secret (EVIDENCE_SIGNING_SECRET). When `None`,
/// key-id equality is not checked (offline auditor may not hold the key;
/// hash + chain still prove internal integrity).
pub fn verify_bundle(bundle: &Value, key: Option<&str>) -> Result<VerifyReport, VerifyError> {
    let obj = bundle.as_object().ok_or(VerifyError::NotAnObject)?;
    let integrity = obj
        .get("integrity")
        .and_then(Value::as_object)
        .ok_or(VerifyError::BadIntegrity)?;
    let expected_bundle_hash = integrity
        .get("bundle_hash")
        .and_then(Value::as_str)
        .ok_or(VerifyError::BadIntegrity)?
        .to_string();
    let expected_chain = integrity
        .get("hash_chain")
        .and_then(Value::as_str)
        .ok_or(VerifyError::BadIntegrity)?
        .to_string();
    let signature = obj
        .get("signature")
        .and_then(Value::as_str)
        .ok_or(VerifyError::MissingField("signature"))?
        .to_string();

    // bundle_hash covers everything except integrity + signature.
    let mut hash_payload = obj.clone();
    hash_payload.remove("integrity");
    hash_payload.remove("signature");
    let computed_bundle_hash = sha256_hex(canonical_json(&Value::Object(hash_payload)).as_bytes());

    // hash_chain folds the evidence records.
    let records = integrity
        .get("records")
        .cloned()
        .unwrap_or_else(|| obj.get("evidence").cloned().unwrap_or(Value::Array(vec![])));
    let record_items: Vec<Value> = records.as_array().cloned().unwrap_or_default();
    let mut current = String::new();
    for item in &record_items {
        current = sha256_hex(format!("{}:{}", current, canonical_json(item)).as_bytes());
    }

    // signature covers the bundle minus signature.
    let mut sig_payload = obj.clone();
    sig_payload.remove("signature");
    let computed_sig = match key {
        Some(k) => hmac_sha256_hex(
            k.as_bytes(),
            canonical_json(&Value::Object(sig_payload)).as_bytes(),
        ),
        None => String::new(),
    };

    let bundle_key_id = integrity
        .get("key_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let key_id_ok = match key {
        Some(k) => bundle_key_id == key_id_for(k),
        None => true, // key not provided: cannot check
    };

    Ok(VerifyReport {
        bundle_hash_ok: computed_bundle_hash == expected_bundle_hash,
        hash_chain_ok: current == expected_chain,
        signature_ok: key.is_none() || computed_sig == signature,
        key_id_ok,
        key_id: bundle_key_id,
        records: record_items.len(),
    })
}
