//! Orchestrate ClickHouse fetch → registry rule → deterministic replay → diff report.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use uuid::Uuid;

use tarka_core::engine::wasm_sandbox::WasmSandboxConfig;
use tarka_core::engine::{Evaluator, FixedClock, TraceContext};
use tarka_core::evidence::Step;
use tarka_core::normalize_otel_trace_id;
use tarka_core::rule_content_sha256;
use tarka_core::SecurityIntegrityViolation;

use crate::clickhouse::{self, EvidenceManifestRow};
use crate::diff::format_diff_report;
use crate::error::CliError;
use crate::mock_external::{mock_external_from_steps, TraceStepJson};
use crate::registry;
use crate::signals::{embedded_rule_content_id, evaluation_payload};
use crate::wasm_loader::load_wasm_modules;

/// Configuration for [`run_forensic_replay`] (constructed from CLI flags).
pub struct ForensicReplayConfig {
    pub manifest_id: Uuid,
    pub clickhouse_url: String,
    pub clickhouse_database: String,
    pub clickhouse_table: String,
    pub clickhouse_user: String,
    pub clickhouse_password: String,
    /// Sets ClickHouse session setting `tarka_tenant_id` when Row-Level Security is enabled.
    pub clickhouse_row_policy_tenant_id: Option<String>,
    pub registry_url: Option<String>,
    pub rule_json_path: Option<PathBuf>,
    pub rule_content_id: Option<String>,
    pub http_timeout: Duration,
    pub http_retries: u32,
    pub wasm_dir: Option<PathBuf>,
    pub strict_timing: bool,
    pub compare_otel: bool,
}

pub async fn run_forensic_replay(cfg: ForensicReplayConfig) -> Result<String, CliError> {
    let http = clickhouse::build_http_client()?;

    let row = clickhouse::fetch_manifest_row(
        &http,
        &cfg.clickhouse_url,
        &cfg.clickhouse_database,
        &cfg.clickhouse_table,
        &cfg.clickhouse_user,
        &cfg.clickhouse_password,
        cfg.manifest_id,
        cfg.http_timeout,
        cfg.http_retries,
        cfg.clickhouse_row_policy_tenant_id.as_deref(),
    )
    .await?;

    let ch_steps = parse_trace_steps(&row)?;
    let original_steps = trace_json_to_proto_steps(&ch_steps);

    let content_id = cfg
        .rule_content_id
        .clone()
        .or_else(|| embedded_rule_content_id(&row.signals))
        .map(|s| s.trim().to_lowercase())
        .ok_or_else(|| {
            CliError::RuleResolution(
                "set `--rule-content-id` or embed `tarka.rule_content_id` in manifest signals"
                    .into(),
            )
        })?;

    validate_content_id_hex(&content_id)?;

    let rule_bytes = resolve_rule_bytes(&cfg, &content_id, &http).await?;

    if cfg.rule_json_path.is_some() {
        let actual = hex::encode(rule_content_sha256(&rule_bytes));
        if actual != content_id {
            return Err(CliError::RuleResolution(format!(
                "SHA-256 of `--rule-json` ({actual}) does not match content id ({content_id})"
            )));
        }
    }

    let payload = evaluation_payload(&row.signals);

    let mock = mock_external_from_steps(&ch_steps);

    let clock: tarka_core::engine::SharedClock =
        Arc::new(FixedClock::from_unix_nanos(row.timestamp_ns as u128));

    let otel = resolve_normalized_otel(&ch_steps);
    let trace = TraceContext::with_clock_and_otel(clock, otel);

    let mut eval = Evaluator::try_from_verified_rule_json(
        &rule_bytes,
        &content_id,
        trace,
        mock,
        row.engine_version.clone(),
    )
    .map_err(|e: SecurityIntegrityViolation| CliError::Core(e.to_string()))?;

    if let Some(dir) = cfg.wasm_dir.as_ref() {
        let reg = load_wasm_modules(dir)?;
        eval = eval
            .with_wasm_modules(reg, WasmSandboxConfig::default())
            .map_err(|e| CliError::Core(format!("wasm registry: {e}")))?;
    }

    let (replay_decision, outcome) = eval.evaluate(&payload);

    let replay_manifest = match outcome {
        Ok(m) => m,
        Err(p) => {
            return Err(CliError::PartialReplay {
                message: p.failure_message.clone(),
                rule_id: p.failing_rule_id.clone(),
            });
        }
    };

    let replay_us = replay_manifest
        .metadata
        .as_ref()
        .map(|m| m.total_execution_time_us)
        .unwrap_or(0);

    let report = format_diff_report(
        cfg.manifest_id,
        row.final_decision != 0,
        row.total_execution_time_us,
        &original_steps,
        replay_decision,
        replay_us,
        &replay_manifest,
        cfg.strict_timing,
        cfg.compare_otel,
    );

    Ok(report)
}

async fn resolve_rule_bytes(
    cfg: &ForensicReplayConfig,
    content_id: &str,
    http: &reqwest::Client,
) -> Result<Vec<u8>, CliError> {
    if let Some(path) = &cfg.rule_json_path {
        let raw = std::fs::read(path).map_err(|e| CliError::RuleFileIo {
            path: path.clone(),
            source: e,
        })?;
        return Ok(raw);
    }

    let base = cfg.registry_url.as_ref().ok_or_else(|| {
        CliError::RuleResolution(
            "either `--rule-json` or `--registry-url` (or env `TARKA_REGISTRY_URL`) is required"
                .into(),
        )
    })?;

    let rr = registry::fetch_rule_by_content_hash(
        http,
        base,
        content_id,
        cfg.http_timeout,
        cfg.http_retries,
    )
    .await?;

    if let Some(h) = rr.content_hash.as_ref() {
        let hl = h.trim().to_lowercase();
        if !hl.is_empty() && hl != content_id {
            return Err(CliError::RuleResolution(format!(
                "registry content_hash {hl} does not match requested id {content_id}"
            )));
        }
    }

    Ok(rr.rule_body.into_bytes())
}

fn validate_content_id_hex(id: &str) -> Result<(), CliError> {
    if id.len() != 64 || !id.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(CliError::RuleResolution(format!(
            "rule content id must be 64 lowercase hex chars (SHA-256), got {:?}",
            id
        )));
    }
    Ok(())
}

fn parse_trace_steps(row: &EvidenceManifestRow) -> Result<Vec<TraceStepJson>, CliError> {
    match &row.trace_json {
        Value::Array(_) => serde_json::from_value(row.trace_json.clone()).map_err(|e| {
            CliError::ClickHousePayload {
                reason: format!("trace_json array decode: {e}"),
            }
        }),
        Value::String(s) => serde_json::from_str(s).map_err(|e| CliError::ClickHousePayload {
            reason: format!("trace_json string decode: {e}"),
        }),
        other => Err(CliError::ClickHousePayload {
            reason: format!("unexpected trace_json shape: {other}"),
        }),
    }
}

fn trace_json_to_proto_steps(steps: &[TraceStepJson]) -> Vec<Step> {
    steps
        .iter()
        .map(|s| {
            let snap: BTreeMap<String, String> = s
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
        .collect()
}

fn resolve_normalized_otel(steps: &[TraceStepJson]) -> Option<String> {
    let raw = steps.iter().find_map(|s| {
        let t = s.otel_trace_id.trim();
        if t.is_empty() {
            None
        } else {
            Some(t.to_string())
        }
    })?;

    match normalize_otel_trace_id(Some(raw.as_str())) {
        Ok(o) => o,
        Err(_) => None,
    }
}
