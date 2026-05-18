//! Compile Protocol Buffers for `tarka-core`.
//!
//! - Crate-local protos: `proto/evidence.proto`, `proto/rule_set.proto` (legacy runtime schema, distinct from wire).
//! - Repository-root wire schema: `proto/tarka/evidence/wire/v1/evidence.proto` (`tarka.evidence.wire.v1`), rebuilt when that file changes.
//!
//! Sets `GIT_HASH` for `env!("GIT_HASH")` in Rust code: use compile-time `GIT_HASH`, else `git rev-parse HEAD`.

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn resolve_git_hash(repo_root: &std::path::Path) -> String {
    if let Ok(v) = env::var("GIT_HASH") {
        let t = v.trim();
        if !t.is_empty() {
            return t.to_string();
        }
    }
    let output = Command::new("git")
        .current_dir(repo_root)
        .args(["rev-parse", "HEAD"])
        .output();
    match output {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => "unknown".to_string(),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    env::set_var("PROTOC", protobuf_src::protoc());

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let crate_proto = manifest_dir.join("proto");
    let repo_root = manifest_dir.join("../..");
    let wire_evidence = repo_root.join("proto/tarka/evidence/wire/v1/evidence.proto");

    let git_hash = resolve_git_hash(&repo_root);
    println!("cargo:rustc-env=GIT_HASH={git_hash}");
    println!("cargo:rerun-if-env-changed=GIT_HASH");
    let git_head = repo_root.join(".git/HEAD");
    if git_head.exists() {
        println!("cargo:rerun-if-changed={}", git_head.display());
    }

    println!("cargo:rerun-if-changed={}", crate_proto.join("evidence.proto").display());
    println!("cargo:rerun-if-changed={}", crate_proto.join("rule_set.proto").display());
    println!("cargo:rerun-if-changed={}", wire_evidence.display());

    let mut config = prost_build::Config::new();
    config.btree_map(["."]);
    config.type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]");

    let includes = vec![
        crate_proto.clone(),
        repo_root.join("proto"),
        protobuf_src::include(),
    ];

    config.compile_protos(
        &[
            crate_proto.join("evidence.proto"),
            crate_proto.join("rule_set.proto"),
            wire_evidence,
        ],
        &includes,
    )?;

    Ok(())
}
