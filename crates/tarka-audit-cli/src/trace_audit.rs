//! ClickHouse + OpenTelemetry correlation audit (legacy `tarka-audit <trace-id>` flow).

use std::time::Duration;

use clap::Parser;
use ed25519_dalek::Signature;
use serde_json::Value;
use tarka_cli::clickhouse::EvidenceManifestRow;
use tarka_cli::mock_external::TraceStepJson;
use tarka_core::evidence::{EvidenceManifest, Step, Trace};
use tarka_core::crypto::{verify_manifest, VerifyError};
use tarka_core::engine::OtelTraceIdError;
use tarka_core::normalize_otel_trace_id;

use crate::ch::{fetch_manifest_for_trace, otel_trace_present, ClickHouseParams};

/// Locate evidence by OpenTelemetry trace id and verify the stored Merkle signature (`TARKA_VERIFYING_KEY`).
#[derive(Parser)]
#[command(about = "Audit tool: OTel spans → ClickHouse manifest → Ed25519ph (legacy internal manifest model).")]
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
    Verify(#[from] VerifyError),
    #[error("signature hex: {0}")]
    SignatureHex(#[from] hex::FromHexError),
    #[error("invalid Ed25519 signature length {0} (expected 64)")]
    SignatureLength(usize),
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

    let row = fetch_manifest_for_trace(
        &http,
        &params,
        &tid,
        cli.ch.latest,
    )
    .await?;

    println!("manifest_id={}", row.manifest_id);
    println!(
        "crypto: algorithm={} key_id={}",
        row.crypto_algorithm, row.crypto_key_id
    );

    let steps = trace_json_to_steps(&row)?;
    let manifest = EvidenceManifest {
        header: None,
        input_map: None,
        trace: Some(Trace { steps }),
        metadata: None,
        crypto_signature: None,
    };

    let sig_hex = row.crypto_signature_hex.trim();
    if sig_hex.is_empty() {
        return Err(AuditError::Msg(
            "manifest has empty crypto_signature_hex; nothing to verify".into(),
        ));
    }

    let sig_bytes = hex::decode(sig_hex)?;
    if sig_bytes.len() != 64 {
        return Err(AuditError::SignatureLength(sig_bytes.len()));
    }
    let sig =
        Signature::from_slice(&sig_bytes).map_err(|_| AuditError::Msg("invalid signature bytes".into()))?;

    verify_manifest(&manifest, &sig)?;
    println!("merkle_signature: OK (Ed25519ph over SHA-512(Merkle root))");
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

fn trace_json_to_steps(row: &EvidenceManifestRow) -> Result<Vec<Step>, AuditError> {
    let ch_steps: Vec<TraceStepJson> = match &row.trace_json {
        Value::Array(_) => serde_json::from_value(row.trace_json.clone()).map_err(|e| {
            AuditError::Msg(format!("trace_json array decode: {e}"))
        }),
        Value::String(s) => serde_json::from_str(s).map_err(|e| {
            AuditError::Msg(format!("trace_json string decode: {e}"))
        }),
        other => Err(AuditError::Msg(format!(
            "unexpected trace_json shape: {other}"
        ))),
    }?;

    Ok(ch_steps
        .iter()
        .map(|s| {
            let snap: std::collections::BTreeMap<String, String> = s
                .state_snapshot
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            Step {
                rule_id: s.rule_id.clone(),
                logic_operator: s.logic_operator.clone(),
                operands: s.operands.clone(),
                result: s.result,
                state_snapshot: snap,
                otel_trace_id: s.otel_trace_id.clone(),
            }
        })
        .collect())
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
}
