//! Evidence bundle verification tests (P1 proof-grade).
//!
//! The fixture bundle is produced by the same algorithm as case-api
//! `_bundle_hash`/`_hash_chain`/`_bundle_signature` (canonical JSON SHA-256,
//! sequential chain, HMAC-SHA256, key-id = sha256(key)[:12]). Parity is the
//! contract: a Python-signed bundle must verify here byte-for-byte.

use serde_json::json;
use tarka_cli::evidence_verify::{key_id_for, verify_bundle};

fn canonical_json(v: &serde_json::Value) -> String {
    // Mirror of the impl under test (sorted keys, compact separators) — used
    // only to build the fixture; verification logic is exercised independently.
    fn sorted(v: &serde_json::Value) -> serde_json::Value {
        match v {
            serde_json::Value::Object(map) => {
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                let mut out = serde_json::Map::new();
                for k in keys {
                    out.insert(k.clone(), sorted(&map[k]));
                }
                serde_json::Value::Object(out)
            }
            serde_json::Value::Array(items) => {
                serde_json::Value::Array(items.iter().map(sorted).collect())
            }
            other => other.clone(),
        }
    }
    serde_json::to_string(&sorted(v)).unwrap()
}

fn sha256_hex(data: &[u8]) -> String {
    use sha2::Digest;
    let mut h = sha2::Sha256::new();
    h.update(data);
    hex::encode(h.finalize())
}

fn hmac_hex(key: &[u8], data: &[u8]) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).unwrap();
    mac.update(data);
    hex::encode(mac.finalize().into_bytes())
}

fn signed_bundle(key: &str, records: Vec<serde_json::Value>) -> serde_json::Value {
    let mut bundle = json!({
        "tenant_id": "t-verify",
        "exported_at": "2026-09-24T00:00:00+00:00",
        "evidence": records,
    });
    // hash chain over records
    let mut current = String::new();
    for item in bundle["evidence"].as_array().unwrap() {
        current = sha256_hex(format!("{}:{}", current, canonical_json(item)).as_bytes());
    }
    // bundle hash over bundle minus integrity+signature (none added yet)
    let bh = sha256_hex(canonical_json(&bundle).as_bytes());
    bundle["integrity"] = json!({
        "algorithm": "sha256+hmac-sha256",
        "key_id": sha256_hex(key.as_bytes())[..12].to_string(),
        "bundle_hash": bh,
        "hash_chain": current,
    });
    let mut sig_payload = bundle.clone();
    sig_payload.as_object_mut().unwrap().remove("signature");
    bundle["signature"] = json!(hmac_hex(
        key.as_bytes(),
        canonical_json(&sig_payload).as_bytes()
    ));
    bundle
}

const KEY: &str = "test-evidence-key-1";

#[test]
fn valid_bundle_verifies_fully() {
    let records = vec![
        json!({"id": "r1", "action": "case.create", "actor": "analyst@a"}),
        json!({"id": "r2", "action": "case.note", "actor": "analyst@a"}),
    ];
    let bundle = signed_bundle(KEY, records);
    let report = verify_bundle(&bundle, Some(KEY)).expect("verify");
    assert!(report.ok(), "all checks pass: {:?}", report);
    assert_eq!(report.records, 2);
    assert_eq!(report.key_id, sha256_hex(KEY.as_bytes())[..12].to_string());
}

#[test]
fn tampered_payload_fails_bundle_hash() {
    let bundle = signed_bundle(KEY, vec![json!({"id": "r1", "action": "case.create"})]);
    let mut tampered = bundle.clone();
    tampered["tenant_id"] = json!("evil-tenant");
    let report = verify_bundle(&tampered, Some(KEY)).expect("verify");
    assert!(!report.bundle_hash_ok, "bundle hash must break");
    assert!(report.hash_chain_ok, "chain untouched");
}

#[test]
fn tampered_record_fails_chain() {
    let bundle = signed_bundle(
        KEY,
        vec![
            json!({"id": "r1", "action": "a"}),
            json!({"id": "r2", "action": "b"}),
        ],
    );
    let mut tampered = bundle.clone();
    tampered["evidence"][1]["action"] = json!("tampered");
    let report = verify_bundle(&tampered, Some(KEY)).expect("verify");
    assert!(!report.hash_chain_ok, "chain must break");
}

#[test]
fn wrong_key_fails_signature_and_key_id() {
    let bundle = signed_bundle(KEY, vec![json!({"id": "r1"})]);
    let report = verify_bundle(&bundle, Some("wrong-key")).expect("verify");
    assert!(
        report.bundle_hash_ok && report.hash_chain_ok,
        "internal integrity holds"
    );
    assert!(!report.signature_ok, "signature must fail");
    assert!(!report.key_id_ok, "key id must mismatch");
}

#[test]
fn no_key_still_proves_internal_integrity() {
    let bundle = signed_bundle(KEY, vec![json!({"id": "r1"})]);
    let report = verify_bundle(&bundle, None).expect("verify");
    assert!(report.bundle_hash_ok && report.hash_chain_ok);
    assert!(report.signature_ok, "no key = signature not checked");
}

#[test]
fn key_id_derivation_matches() {
    assert_eq!(
        key_id_for(KEY),
        sha256_hex(KEY.as_bytes())[..12].to_string()
    );
}
