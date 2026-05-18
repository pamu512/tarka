//! Deterministic sealed wire manifest for `crates/tarka-py/tests/test_integrity_parity.py`.
//!
//! Regenerate the fixture after changing wire hashing, seal layout, or this generator:
//! ```text
//! cargo run -p tarka-core --example gen_pytest_golden_manifest -- \
//!   ../../crates/tarka-py/tests/fixtures/golden_sealed_manifest.pb
//! ```
//!
//! The program prints `GOLDEN_*` lines to paste into the Python test.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::Path;

use ed25519_dalek::SigningKey;
use prost::Message;
use sha2::{Digest, Sha256};
use tarka_core::evidence::merkle::try_generate_trace_merkle_proof;
use tarka_core::evidence::TarkaEvidence;
use tarka_core::pb::signal_value::Value;
use tarka_core::pb::{EngineMetadata, EvidenceManifest, SignalValue};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out_path = env::args()
        .nth(1)
        .ok_or("usage: gen_pytest_golden_manifest <output.pb>")?;
    let out = Path::new(&out_path);

    let mut signals = BTreeMap::new();
    signals.insert(
        "parity_k".into(),
        SignalValue {
            source: "golden-src".into(),
            value: Some(Value::NumVal(0.25)),
        },
    );

    let manifest = EvidenceManifest {
        manifest_id: "018f1234-5678-7abc-8def-123456789abc".into(),
        occurred_at_unix_ns: 17_000_000_000_000,
        engine: Some(EngineMetadata {
            version: "golden".into(),
            git_hash: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
            environment: String::new(),
            engine_instance_id: String::new(),
        }),
        signals,
        trace: vec![],
        verdict: None,
        merkle_root: vec![],
        signature: vec![],
        merkle_proof: None,
    };

    let mut tarka = TarkaEvidence { manifest };
    let seed = [0x5Eu8; 32];
    let sk = SigningKey::from_bytes(&seed);
    tarka.seal(&sk)?;
    let proof = try_generate_trace_merkle_proof(&tarka.manifest.trace)?;
    tarka.manifest.merkle_proof = Some(proof);

    let encoded = tarka.manifest.encode_to_vec();
    if let Some(parent) = out.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(out, &encoded)?;

    let digest = Sha256::digest(&encoded);
    let vk = sk.verifying_key();
    println!("GOLDEN_MANIFEST_SHA256={}", hex::encode(digest));
    println!(
        "GOLDEN_MERKLE_ROOT_HEX={}",
        hex::encode(tarka.manifest.merkle_root.as_slice())
    );
    println!("GOLDEN_VERIFYING_KEY_HEX={}", hex::encode(vk.to_bytes()));

    Ok(())
}
