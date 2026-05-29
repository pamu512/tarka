//! ClickHouse + OpenTelemetry correlation audit (`tarka-audit trace <trace-id>`).

use std::path::PathBuf;
use std::time::Duration;

use clap::Parser;
use serde_json::Value;
use tarka_cli::clickhouse::EvidenceManifestRow;
use tarka_core::crypto::{verifying_key_from_env, CryptoError};
use tarka_core::engine::OtelTraceIdError;
use tarka_core::evidence::wire_integrity::{
    verify_wire_manifest_integrity, WireManifestVerifyFailure,
};
use tarka_core::normalize_otel_trace_id;

use crate::ch::{clickhouse_column_exists, fetch_manifest_for_trace, otel_trace_present, ClickHouseParams};

/// Locate evidence by OpenTelemetry trace id and verify sealed wire manifest bytes (`TARKA_VERIFYING_KEY`).
#[derive(Parser)]
#[command(
    about = "Audit tool: OTel spans → ClickHouse manifest → wire EvidenceManifest integrity (ManifestVerifier parity)."
)]
pub struct TraceCli {
    /// W3C trace id (32 hex chars, case-insensitive). UUID-with-dashes form is accepted.
    pub trace_id: String,

    #[command(flatten)]
    pub ch: ChArgs,
}

#[derive(Parser)]
pub struct ChArgs {
    #[arg(long, env = "CLICKHOUSE_HTTP_URL", default_value = "http://127.0.0.1:8123")]
    pub clickhouse_url: String,

    #[arg(long, env = "CLICKHOUSE_DATABASE", default_value = "tarka_audit")]
    pub clickhouse_database: String,

    #[arg(long, env = "CLICKHOUSE_TABLE", default_value = "evidence_manifests")]
    pub clickhouse_table: String,

    #[arg(
        long,
        env = "CLICKHOUSE_OTEL_SPANS_TABLE",
        default_value = "otel_spans"
    )]
    pub clickhouse_otel_spans_table: String,

    #[arg(long, env = "CLICKHOUSE_USER", default_value = "default")]
    pub clickhouse_user: String,

    #[arg(long, env = "CLICKHOUSE_PASSWORD", default_value = "")]
    pub clickhouse_password: String,

    #[arg(long, env = "CLICKHOUSE_ROW_POLICY_TENANT_ID")]
    pub clickhouse_row_policy_tenant_id: Option<String>,

    #[arg(long, default_value_t = 45)]
    pub http_timeout_secs: u64,

    #[arg(long, default_value_t = 3)]
    pub http_retries: u32,

    /// When several manifests reference this trace id, select the one with the greatest `timestamp_ns`.
    #[arg(long, default_value_t = false)]
    pub latest: bool,

    /// Optional path to on-disk wire manifest bytes when ClickHouse has no `raw_manifest` column.
    #[arg(long, env = "VERIFY_STACK_MANIFEST_PATH")]
    pub manifest_path: Option<PathBuf>,
}

#[derive(Debug, thiserror::Error)]
pub enum AuditError {
    #[error("invalid trace id: {0}")]
    TraceId(#[from] OtelTraceIdError),
    #[error("{0}")]
    Msg(String),
    #[error(transparent)]
    ClickHouse(#[from] crate::ch::ClickHouseError),
    #[error(transparent)]
    Crypto(#[from] CryptoError),
    #[error(transparent)]
    WireVerify(#[from] WireManifestVerifyFailure),
    #[error("wire manifest hex: {0}")]
    WireHex(#[from] hex::FromHexError),
}

pub fn run(cli: TraceCli) -> Result<(), AuditError> {
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .map_err(|e| AuditError::Msg(format!("tokio runtime: {e}")))?;
    rt.block_on(run_async(cli))
}

async fn run_async(cli: TraceCli) -> Result<(), AuditError> {
    let tid = normalize_cli_trace_id(&cli.trace_id)?;
    let timeout = Duration::from_secs(cli.ch.http_timeout_secs);
    let params = ClickHouseParams {
        base_url: cli.ch.clickhouse_url.clone(),
        database: cli.ch.clickhouse_database.clone(),
        evidence_table: cli.ch.clickhouse_table.clone(),
        otel_spans_table: cli.ch.clickhouse_otel_spans_table.clone(),
        user: cli.ch.clickhouse_user.clone(),
        password: cli.ch.clickhouse_password.clone(),
        row_policy_tenant_id: cli.ch.clickhouse_row_policy_tenant_id.clone(),
        timeout,
        max_retries: cli.ch.http_retries,
    };

    let http = crate::ch::build_http_client()?;

    let otel = otel_trace_present(&http, &params, &tid).await?;
    println!(
        "otel_spans: count={} min_ts={} max_ts={}",
        otel.span_count,
        otel.min_timestamp.as_deref().unwrap_or("-"),
        otel.max_timestamp.as_deref().unwrap_or("-"),
    );
    if otel.span_count == 0 {
        return Err(AuditError::Msg(format!(
            "no spans in `{database}`.`{otel}` for TraceId={tid} (cannot anchor audit to OTel)",
            database = params.database,
            otel = params.otel_spans_table,
        )));
    }

    let has_raw_col = clickhouse_column_exists(
        &http,
        &params,
        &params.evidence_table,
        "raw_manifest",
    )
    .await?;

    let row = fetch_manifest_for_trace(
        &http,
        &params,
        &tid,
        cli.ch.latest,
        has_raw_col,
    )
    .await?;

    println!("manifest_id={}", row.manifest_id);
    println!(
        "crypto: algorithm={} key_id={}",
        row.crypto_algorithm, row.crypto_key_id
    );

    let wire_bytes = resolve_wire_manifest_bytes(&row, cli.ch.manifest_path.as_deref())?;
    let vk = verifying_key_from_env()?;
    let pk = vk.to_bytes();
    verify_wire_manifest_integrity(&wire_bytes, &pk)?;
    println!("wire manifest: OK (matches Python ManifestVerifier semantics)");
    Ok(())
}

fn normalize_cli_trace_id(raw: &str) -> Result<String, OtelTraceIdError> {
    let t = raw.trim();
    if t.is_empty() {
        return Err(OtelTraceIdError::InvalidLength { len: 0 });
    }
    let compact: String = if t.len() == 36 && t.bytes().filter(|b| *b == b'-').count() == 4 {
        t.chars().filter(|c| *c != '-').collect()
    } else {
        t.to_string()
    };
    let Some(norm) = normalize_otel_trace_id(Some(compact.as_str()))? else {
        return Err(OtelTraceIdError::InvalidLength {
            len: compact.len(),
        });
    };
    Ok(norm)
}

fn resolve_wire_manifest_bytes(
    row: &EvidenceManifestRow,
    manifest_path: Option<&std::path::Path>,
) -> Result<Vec<u8>, AuditError> {
    if let Some(hex_raw) = row.raw_manifest_hex.as_deref() {
        let trimmed = hex_raw.trim();
        if !trimmed.is_empty() {
            let wire = hex::decode(trimmed)?;
            if !wire.is_empty() {
                return Ok(wire);
            }
        }
    }

    let path = manifest_path
        .map(|p| p.to_path_buf())
        .or_else(|| {
            std::env::var("VERIFY_STACK_MANIFEST_PATH")
                .ok()
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from)
        });

    let Some(path) = path else {
        return Err(AuditError::Msg(
            "no wire manifest bytes available: add nullable binary column `raw_manifest` to \
             evidence_manifests (preferred), or pass --manifest-path / set VERIFY_STACK_MANIFEST_PATH \
             to on-disk wire EvidenceManifest bytes whose SHA-256 matches raw_manifest_sha256 in ClickHouse"
                .into(),
        ));
    };

    if !path.is_file() {
        return Err(AuditError::Msg(format!(
            "manifest path is not a file: {}",
            path.display()
        )));
    }

    let wire = std::fs::read(&path).map_err(|e| {
        AuditError::Msg(format!("read manifest {}: {e}", path.display()))
    })?;

    let digest = sha256_bytes(&wire);
    let expected = parse_sha256_hex(
        row.raw_manifest_sha256_hex
            .as_deref()
            .or(row.raw_manifest_sha256.as_deref()),
    )?;
    let Some(expected) = expected else {
        return Err(AuditError::Msg(
            "ClickHouse row missing raw_manifest_sha256_hex; cannot validate file binding".into(),
        ));
    };
    if digest != expected {
        return Err(AuditError::Msg(format!(
            "manifest file SHA-256 does not match ClickHouse raw_manifest_sha256 \
             (file={} ch={})",
            hex::encode(digest),
            hex::encode(expected),
        )));
    }

    Ok(wire)
}

fn sha256_bytes(data: &[u8]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(data);
    h.finalize().into()
}

fn parse_sha256_hex(raw: Option<&str>) -> Result<Option<[u8; 32]>, AuditError> {
    let Some(s) = raw.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(None);
    };
    let lower = s.to_ascii_lowercase();
    if lower.len() != 64 || !lower.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(AuditError::Msg(format!(
            "invalid raw_manifest_sha256 hex (expected 64 chars, got {})",
            lower.len()
        )));
    }
    let bytes = hex::decode(lower)?;
    let arr: [u8; 32] = bytes
        .try_into()
        .map_err(|v: Vec<u8>| AuditError::Msg(format!("sha256 digest length {}", v.len())))?;
    Ok(Some(arr))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_uuid_trace_id() {
        let u = "550e8400-e29b-41d4-a716-446655440000";
        let n = normalize_cli_trace_id(u).expect("ok");
        assert_eq!(n.len(), 32);
        assert!(n.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn resolve_wire_prefers_clickhouse_hex() {
        let row = EvidenceManifestRow {
            tenant_id: String::new(),
            manifest_id: "550e8400-e29b-41d4-a716-446655440000".into(),
            engine_version: String::new(),
            timestamp_ns: 0,
            final_decision: 0,
            total_execution_time_us: 0,
            signals: serde_json::Map::new(),
            trace_json: Value::Null,
            crypto_algorithm: String::new(),
            crypto_signature_hex: String::new(),
            crypto_key_id: String::new(),
            raw_manifest_sha256: None,
            raw_manifest_hex: Some(hex::encode([7u8; 64])),
            raw_manifest_sha256_hex: None,
        };
        let wire = resolve_wire_manifest_bytes(&row, None).expect("hex");
        assert_eq!(wire.len(), 64);
        assert_eq!(wire[0], 7);
    }
}
