//! Fuzz the Protobuf **`EvidenceManifest`** decoder (`prost`) with arbitrary bytes.
//!
//! Corrupted audit / ingest payloads must **never** panic the Rust runtime — decoding should
//! surface [`prost::DecodeError`] (or succeed). This target feeds libFuzzer input directly into
//! [`prost::Message::decode`].
//!
//! ## Running
//!
//! ```text
//! cargo install cargo-fuzz
//! cd fuzz && cargo fuzz run evidence_manifest_decode -- -runs=1000000
//! ```

#![no_main]

use libfuzzer_sys::fuzz_target;
use prost::Message;
use tarka_core::evidence::EvidenceManifest;

fuzz_target!(|data: &[u8]| {
    let _ = EvidenceManifest::decode(data);
});
