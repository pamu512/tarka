//! `tarka-audit` — wire manifest verification (independent auditor, Python parity) and optional ClickHouse trace audit.

mod ch;
mod trace_audit;

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use tarka_core::evidence::wire_integrity::verify_wire_manifest_integrity;

#[derive(Parser)]
#[command(name = "tarka-audit")]
#[command(
    about = "Audit CLI: verify sealed wire EvidenceManifest bytes (same checks as Python ManifestVerifier), or correlate OTel spans with ClickHouse manifests.",
    version,
    propagate_version = true
)]
struct RootCli {
    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Verify raw `.bin` wire manifest bytes against an Ed25519 public key (parity with Python `ManifestVerifier.verify_manifest_integrity`).
    Verify(VerifyCli),
    /// Legacy: locate evidence by OpenTelemetry trace id in ClickHouse and verify the internal Merkle signature.
    Trace(trace_audit::TraceCli),
}

#[derive(Parser)]
struct VerifyCli {
    /// Path to raw protobuf bytes (`EvidenceManifest` on the wire, e.g. `.bin`).
    manifest: PathBuf,

    /// Ed25519 verifying key as 64 hex characters (32 bytes). Optional `0x` prefix.
    #[arg(long = "public-key", value_name = "HEX")]
    public_key: String,
}

fn main() -> ExitCode {
    let root = RootCli::parse();
    match root.cmd {
        Command::Verify(v) => verify_manifest_cmd(v),
        Command::Trace(t) => match trace_audit::run(t) {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("{e}");
                ExitCode::from(1)
            }
        },
    }
}

fn verify_manifest_cmd(cli: VerifyCli) -> ExitCode {
    let bytes = match std::fs::read(&cli.manifest) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("failed to read manifest {}: {e}", cli.manifest.display());
            return ExitCode::from(1);
        }
    };

    let pk = match parse_hex_public_key(&cli.public_key) {
        Ok(k) => k,
        Err(msg) => {
            eprintln!("{msg}");
            return ExitCode::from(1);
        }
    };

    match verify_wire_manifest_integrity(&bytes, &pk) {
        Ok(()) => {
            println!("wire manifest: OK (matches Python ManifestVerifier semantics)");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(1)
        }
    }
}

fn parse_hex_public_key(raw: &str) -> Result<[u8; 32], String> {
    let mut s = raw.trim();
    if let Some(rest) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
        s = rest.trim_start();
    }
    s = s.trim();
    if s.len() != 64 {
        return Err(format!(
            "public key must be 64 hex characters (32 bytes); got {} characters",
            s.len()
        ));
    }
    if !s.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("public key hex contains non-hexadecimal characters".into());
    }
    let vec = hex::decode(s).map_err(|e| format!("public key hex decode: {e}"))?;
    let vec: [u8; 32] = vec
        .try_into()
        .map_err(|v: Vec<u8>| format!("expected 32 bytes after decode, got {}", v.len()))?;
    Ok(vec)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_hex_key_with_0x() {
        let hex = "00".repeat(32);
        let k = parse_hex_public_key(&format!("0x{hex}")).expect("ok");
        assert_eq!(k, [0u8; 32]);
    }
}
