//! Orchestrate ClickHouse fetch → registry rule → deterministic replay → diff report.

use std::collections::BTreeMap;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use rayon::prelude::*;
use rayon::ThreadPoolBuilder;
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use tarka_core::engine::wasm_sandbox::WasmSandboxConfig;
use tarka_core::engine::{Evaluator, FixedClock, TraceContext};
use tarka_core::evidence::signal_value::Value as SignalScalar;
use tarka_core::evidence::{
    CryptoSignature, EvidenceManifest, Header, InputMap, Metadata, SignalValue, Step, Trace,
};
use tarka_core::normalize_otel_trace_id;
use tarka_core::rule_content_sha256;
use tarka_core::SecurityIntegrityViolation;
use tarka_core::TarkaCoreError;

use crate::clickhouse::{self, ClickhouseClient, EvidenceManifestRow};
use crate::diff::format_diff_report;
use crate::error::CliError;
use crate::mock_external::{mock_external_from_steps, TraceStepJson};
use crate::registry;
use crate::scorecard::{
    EvaluatedManifestRecord, MismatchCollector, ReplayScorecard, ScorecardCollector,
    TraceMismatchCapture,
};
use crate::signals::{embedded_rule_content_id, evaluation_payload, normalize_signal_value};
use crate::wasm_loader::load_wasm_modules;

pub use clickhouse::{MANIFEST_BATCH_STREAM_CHUNK, MAX_MANIFEST_BATCH_WINDOW_PULL};

/// Validated inputs for tenant-scoped batch forensic replay.
#[derive(Debug, Clone)]
pub struct BatchReplayConfig {
    pub since_rfc3339: String,
    pub until_rfc3339: String,
    pub since_unix_ns: i64,
    pub until_unix_ns: i64,
    pub tenant_id: String,
    pub concurrency: usize,
    pub clickhouse_url: String,
    pub clickhouse_database: String,
    pub clickhouse_table: String,
    pub clickhouse_user: String,
    pub clickhouse_password: String,
    pub normalized_labels_table: String,
    pub http_timeout: Duration,
    pub http_retries: u32,
    pub registry_url: Option<String>,
    pub rule_json_path: Option<PathBuf>,
    pub rule_content_id: Option<String>,
    pub wasm_dir: Option<PathBuf>,
    pub strict_timing: bool,
    pub compare_otel: bool,
}

/// Outcome of replaying one loaded manifest inside a batch worker.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct BatchManifestReplayOutcome {
    pub manifest_id: String,
    pub status: BatchReplayStatus,
    pub original_decision: Option<bool>,
    pub replay_decision: Option<bool>,
    pub decision_match: bool,
    pub step_parity: bool,
    pub transaction_id: Option<String>,
    pub ground_truth_fraud: Option<bool>,
    pub diverged_rules: Vec<String>,
    pub diff_trace: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BatchReplayStatus {
    Match,
    Mismatch,
    Partial,
    Error,
}

struct BatchReplayExecutionContext {
    concurrency: usize,
    forced_content_id: Option<String>,
    rules: Arc<HashMap<String, Arc<[u8]>>>,
    wasm_modules: Option<Arc<HashMap<String, Arc<[u8]>>>>,
    strict_timing: bool,
    compare_otel: bool,
    ground_truth_labels: Arc<HashMap<String, bool>>,
}

/// Parse RFC3339 datetimes, stream manifests for the tenant window in bounded chunks, and build a replay scorecard.
pub async fn run_batch_replay(cfg: BatchReplayConfig) -> Result<ReplayScorecard, CliError> {
    let started = Instant::now();

    let ch_client = ClickhouseClient::try_new(
        &cfg.clickhouse_url,
        &cfg.clickhouse_database,
        &cfg.clickhouse_table,
        &cfg.clickhouse_user,
        &cfg.clickhouse_password,
        cfg.http_timeout,
        cfg.http_retries,
    )?;

    let prefetch = prefetch_batch_window_metadata(
        &ch_client,
        cfg.since_unix_ns,
        cfg.until_unix_ns,
        &cfg.tenant_id,
        cfg.rule_content_id.as_deref(),
    )
    .await
    .map_err(|e| CliError::BatchReplay(e.to_string()))?;

    if prefetch.total_manifests == 0 {
        return Ok(
            ScorecardCollector::new().into_replay_scorecard(0, Duration::ZERO),
        );
    }

    let ground_truth_labels = Arc::new(
        ch_client
            .fetch_active_ground_truth_labels(
                &cfg.tenant_id,
                &cfg.normalized_labels_table,
                &prefetch.transaction_ids,
            )
            .await
            .map_err(|e| CliError::BatchReplay(e.to_string()))?,
    );

    let rule_catalog = resolve_batch_rule_catalog(&cfg, &prefetch.content_ids).await?;
    let wasm_modules = if let Some(dir) = cfg.wasm_dir.as_ref() {
        Some(Arc::new(load_wasm_modules(dir)?))
    } else {
        None
    };

    let exec_ctx = Arc::new(BatchReplayExecutionContext {
        concurrency: cfg.concurrency,
        forced_content_id: cfg
            .rule_content_id
            .as_ref()
            .map(|s| s.trim().to_lowercase()),
        rules: rule_catalog,
        wasm_modules,
        strict_timing: cfg.strict_timing,
        compare_otel: cfg.compare_otel,
        ground_truth_labels,
    });

    let mut collector = ScorecardCollector::new();
    let mut cursor: Option<clickhouse::ManifestWindowBookmark> = None;
    let mut worker_elapsed = Duration::ZERO;

    loop {
        let chunk = ch_client
            .fetch_manifest_rows_window_page(
                cfg.since_unix_ns,
                cfg.until_unix_ns,
                &cfg.tenant_id,
                cursor.as_ref(),
                MANIFEST_BATCH_STREAM_CHUNK,
            )
            .await
            .map_err(|e| CliError::BatchReplay(e.to_string()))?;

        if chunk.is_empty() {
            break;
        }

        cursor = chunk.last().map(clickhouse::ManifestWindowBookmark::from_row);
        let manifests = rows_to_evidence_manifests(&chunk)
            .map_err(|e| CliError::BatchReplay(e.to_string()))?;
        let ctx = Arc::clone(&exec_ctx);
        let chunk_started = Instant::now();
        let chunk_collector = tokio::task::spawn_blocking(move || {
            execute_batch_replay_parallel(manifests, ctx)
        })
        .await
        .map_err(|e| CliError::BatchReplay(format!("batch replay worker join failed: {e}")))?;
        worker_elapsed += chunk_started.elapsed();
        collector = collector.merge(chunk_collector);

        if chunk.len() < MANIFEST_BATCH_STREAM_CHUNK {
            break;
        }
    }

    let execution_time_ms = started.elapsed().as_millis() as u64;
    Ok(collector.into_replay_scorecard(execution_time_ms, worker_elapsed))
}

#[derive(Debug, Clone, Default)]
struct BatchWindowPrefetch {
    total_manifests: usize,
    transaction_ids: Vec<String>,
    content_ids: HashSet<String>,
}

async fn prefetch_batch_window_metadata(
    ch_client: &ClickhouseClient,
    start_ts: i64,
    end_ts: i64,
    tenant_id: &str,
    forced_content_id: Option<&str>,
) -> Result<BatchWindowPrefetch, TarkaCoreError> {
    validate_window_bounds(start_ts, end_ts)?;
    if tenant_id.trim().is_empty() {
        return Err(TarkaCoreError::EmptyTenantId);
    }

    let mut prefetch = BatchWindowPrefetch {
        total_manifests: 0,
        transaction_ids: Vec::with_capacity(MANIFEST_BATCH_STREAM_CHUNK),
        content_ids: HashSet::with_capacity(MANIFEST_BATCH_STREAM_CHUNK / 4),
    };
    let mut txn_seen = HashSet::with_capacity(MANIFEST_BATCH_STREAM_CHUNK);

    ch_client
        .stream_manifest_rows_by_window(
            start_ts,
            end_ts,
            tenant_id,
            MANIFEST_BATCH_STREAM_CHUNK,
            |chunk| {
                prefetch.total_manifests += chunk.len();
                accumulate_prefetch_from_rows(
                    &chunk,
                    forced_content_id,
                    &mut prefetch.content_ids,
                    &mut prefetch.transaction_ids,
                    &mut txn_seen,
                );
                Ok(())
            },
        )
        .await
        .map_err(cli_error_to_core)?;

    prefetch.transaction_ids.sort_unstable();
    Ok(prefetch)
}

fn accumulate_prefetch_from_rows(
    rows: &[EvidenceManifestRow],
    forced_content_id: Option<&str>,
    content_ids: &mut HashSet<String>,
    transaction_ids: &mut Vec<String>,
    txn_seen: &mut HashSet<String>,
) {
    for row in rows {
        if let Some(id) = clickhouse::transaction_id_from_signal_map(&row.signals) {
            if txn_seen.insert(id.clone()) {
                transaction_ids.push(id);
            }
        }
        if let Some(content_id) = forced_content_id
            .map(|s| s.trim().to_lowercase())
            .filter(|s| !s.is_empty())
            .or_else(|| embedded_rule_content_id(&row.signals))
        {
            content_ids.insert(content_id);
        }
    }
}

fn rows_to_evidence_manifests(rows: &[EvidenceManifestRow]) -> Result<Vec<EvidenceManifest>, TarkaCoreError> {
    let mut manifests = Vec::with_capacity(rows.len());
    for row in rows {
        manifests.push(row_to_evidence_manifest(row)?);
    }
    Ok(manifests)
}

fn evaluated_record_from_outcome(outcome: &BatchManifestReplayOutcome) -> EvaluatedManifestRecord {
    EvaluatedManifestRecord {
        manifest_id: outcome.manifest_id.clone(),
        historical_decision: outcome.original_decision,
        new_decision: outcome.replay_decision,
        decision_match: outcome.decision_match,
        step_parity: outcome.step_parity,
        transaction_id: outcome.transaction_id.clone(),
        ground_truth_fraud: outcome.ground_truth_fraud,
        diverged_rules: outcome.diverged_rules.clone(),
        diff_trace: outcome.diff_trace.clone(),
        error: outcome.error.clone(),
    }
}

fn resolve_ground_truth_for_manifest(
    manifest: &EvidenceManifest,
    ground_truth_labels: &HashMap<String, bool>,
) -> (Option<String>, Option<bool>) {
    let signals = signals_map_from_manifest(manifest);
    let transaction_id = clickhouse::transaction_id_from_signal_map(&signals);
    let ground_truth_fraud = transaction_id
        .as_ref()
        .and_then(|id| ground_truth_labels.get(id).copied());
    (transaction_id, ground_truth_fraud)
}

fn build_batch_outcome(
    manifest_id: String,
    status: BatchReplayStatus,
    historical_decision: Option<bool>,
    new_decision: Option<bool>,
    decision_match: bool,
    step_parity: bool,
    transaction_id: Option<String>,
    ground_truth_fraud: Option<bool>,
    historical_steps: &[Step],
    new_steps: &[Step],
    compare_otel: bool,
    error: Option<String>,
) -> BatchManifestReplayOutcome {
    let (diverged_rules, diff_trace) = if status == BatchReplayStatus::Match {
        (Vec::new(), String::new())
    } else {
        let detail = MismatchCollector::collect(TraceMismatchCapture {
            manifest_id: manifest_id.clone(),
            historical_decision,
            new_decision,
            historical_steps: historical_steps.to_vec(),
            new_steps: new_steps.to_vec(),
            compare_otel,
            error: error.clone(),
        });
        (detail.diverged_rules, detail.diff_trace)
    };

    BatchManifestReplayOutcome {
        manifest_id,
        status,
        original_decision: historical_decision,
        replay_decision: new_decision,
        decision_match,
        step_parity,
        transaction_id,
        ground_truth_fraud,
        diverged_rules,
        diff_trace,
        error,
    }
}

/// Parallel batch replay with lock-free per-shard [`ScorecardCollector`] fold/reduce (no mutex hot path).
fn execute_batch_replay_parallel(
    manifests: Vec<EvidenceManifest>,
    ctx: Arc<BatchReplayExecutionContext>,
) -> ScorecardCollector {
    let pool = ThreadPoolBuilder::new()
        .num_threads(ctx.concurrency.max(1))
        .build()
        .expect("rayon thread pool must initialize");

    pool.install(|| {
        manifests
            .into_par_iter()
            .map(|manifest| replay_loaded_manifest(&manifest, &ctx))
            .fold(
                ScorecardCollector::new,
                |mut collector, outcome| {
                    collector.record_evaluated(evaluated_record_from_outcome(&outcome));
                    collector
                },
            )
            .reduce(ScorecardCollector::new, |left, right| left.merge(right))
    })
}

fn replay_loaded_manifest(
    manifest: &EvidenceManifest,
    ctx: &BatchReplayExecutionContext,
) -> BatchManifestReplayOutcome {
    let historical_decision = manifest.metadata.as_ref().map(|m| m.final_decision);
    let historical_steps = manifest
        .trace
        .as_ref()
        .map(|t| t.steps.as_slice())
        .unwrap_or(&[]);
    let (transaction_id, ground_truth_fraud) =
        resolve_ground_truth_for_manifest(manifest, &ctx.ground_truth_labels);

    let manifest_id = match manifest_uuid_from_header(manifest) {
        Ok(id) => id.hyphenated().to_string(),
        Err(err) => {
            return build_batch_outcome(
                "unknown".into(),
                BatchReplayStatus::Error,
                historical_decision,
                None,
                false,
                false,
                transaction_id,
                ground_truth_fraud,
                historical_steps,
                &[],
                ctx.compare_otel,
                Some(err.to_string()),
            );
        }
    };

    let original_decision = historical_decision;
    let original_exec_us = manifest
        .metadata
        .as_ref()
        .map(|m| m.total_execution_time_us)
        .unwrap_or(0);
    let original_steps = historical_steps;

    let content_id = match resolve_content_id_for_manifest(manifest, ctx.forced_content_id.as_deref())
    {
        Ok(id) => id,
        Err(err) => {
            return build_batch_outcome(
                manifest_id,
                BatchReplayStatus::Error,
                original_decision,
                None,
                false,
                false,
                transaction_id,
                ground_truth_fraud,
                original_steps,
                &[],
                ctx.compare_otel,
                Some(err.to_string()),
            );
        }
    };

    let rule_bytes = match ctx.rules.get(&content_id) {
        Some(bytes) => bytes.as_ref(),
        None => {
            return build_batch_outcome(
                manifest_id,
                BatchReplayStatus::Error,
                original_decision,
                None,
                false,
                false,
                transaction_id,
                ground_truth_fraud,
                original_steps,
                &[],
                ctx.compare_otel,
                Some(format!("rule bytes not loaded for content id {content_id}")),
            );
        }
    };

    let signals = signals_map_from_manifest(manifest);
    let trace_json_steps = steps_to_trace_json(original_steps);
    let payload = evaluation_payload(&signals);
    let mock = mock_external_from_steps(&trace_json_steps);

    let timestamp_ns = manifest
        .header
        .as_ref()
        .map(|h| h.timestamp_ns)
        .unwrap_or(0);
    let clock: tarka_core::engine::SharedClock =
        Arc::new(FixedClock::from_unix_nanos(timestamp_ns as u128));
    let otel = resolve_normalized_otel(&trace_json_steps);
    let trace = TraceContext::with_clock_and_otel(clock, otel);
    let engine_version = manifest
        .header
        .as_ref()
        .map(|h| h.engine_version.clone())
        .unwrap_or_default();

    let mut eval = match Evaluator::try_from_verified_rule_json(
        rule_bytes,
        &content_id,
        trace,
        mock,
        engine_version,
    ) {
        Ok(eval) => eval,
        Err(err) => {
            return build_batch_outcome(
                manifest_id,
                BatchReplayStatus::Error,
                original_decision,
                None,
                false,
                false,
                transaction_id,
                ground_truth_fraud,
                original_steps,
                &[],
                ctx.compare_otel,
                Some(err.to_string()),
            );
        }
    };

    if let Some(wasm_modules) = ctx.wasm_modules.as_ref() {
        match eval.with_wasm_modules((**wasm_modules).clone(), WasmSandboxConfig::default()) {
            Ok(next) => eval = next,
            Err(err) => {
                return build_batch_outcome(
                    manifest_id,
                    BatchReplayStatus::Error,
                    original_decision,
                    None,
                    false,
                    false,
                    transaction_id,
                    ground_truth_fraud,
                    original_steps,
                    &[],
                    ctx.compare_otel,
                    Some(format!("wasm registry: {err}")),
                );
            }
        }
    }

    let (replay_decision, outcome) = eval.evaluate(&payload);
    let replay_manifest = match outcome {
        Ok(manifest) => manifest,
        Err(partial) => {
            let partial_steps = partial
                .evidence
                .trace
                .as_ref()
                .map(|t| t.steps.as_slice())
                .unwrap_or(&[]);
            let error = format!(
                "{} (rule={:?})",
                partial.failure_message, partial.failing_rule_id
            );
            return build_batch_outcome(
                manifest_id,
                BatchReplayStatus::Partial,
                original_decision,
                Some(replay_decision),
                original_decision == Some(replay_decision),
                false,
                transaction_id,
                ground_truth_fraud,
                original_steps,
                partial_steps,
                ctx.compare_otel,
                Some(error),
            );
        }
    };

    let replay_exec_us = replay_manifest
        .metadata
        .as_ref()
        .map(|m| m.total_execution_time_us)
        .unwrap_or(0);
    let replay_steps = replay_manifest
        .trace
        .as_ref()
        .map(|t| t.steps.as_slice())
        .unwrap_or(&[]);

    let decision_matches = original_decision == Some(replay_decision);
    let timing_matches = !ctx.strict_timing || original_exec_us == replay_exec_us;
    let trace_matches = trace_steps_equivalent(
        original_steps,
        replay_steps,
        ctx.compare_otel,
    );

    let status = if decision_matches && timing_matches && trace_matches {
        BatchReplayStatus::Match
    } else {
        BatchReplayStatus::Mismatch
    };

    build_batch_outcome(
        manifest_id,
        status,
        original_decision,
        Some(replay_decision),
        decision_matches,
        trace_matches,
        transaction_id,
        ground_truth_fraud,
        original_steps,
        replay_steps,
        ctx.compare_otel,
        None,
    )
}

async fn resolve_batch_rule_catalog(
    cfg: &BatchReplayConfig,
    content_ids: &HashSet<String>,
) -> Result<Arc<HashMap<String, Arc<[u8]>>>, CliError> {
    let http = clickhouse::build_http_client()?;
    let mut catalog: HashMap<String, Arc<[u8]>> = HashMap::with_capacity(content_ids.len());

    if let Some(path) = &cfg.rule_json_path {
        let content_id = cfg.rule_content_id.as_ref().ok_or_else(|| {
            CliError::RuleResolution(
                "batch-replay with --rule-json requires --rule-content-id (or TARKA_RULE_CONTENT_ID)"
                    .into(),
            )
        })?;
        let content_id = content_id.trim().to_lowercase();
        validate_content_id_hex(&content_id)?;
        let raw = std::fs::read(path).map_err(|source| CliError::RuleFileIo {
            path: path.clone(),
            source,
        })?;
        let actual = hex::encode(rule_content_sha256(&raw));
        if actual != content_id {
            return Err(CliError::RuleResolution(format!(
                "SHA-256 of --rule-json ({actual}) does not match content id ({content_id})"
            )));
        }
        catalog.insert(content_id, raw.into());
        return Ok(Arc::new(catalog));
    }

    if content_ids.is_empty() {
        return Err(CliError::RuleResolution(
            "no rule content ids found in batch manifests; pass --rule-content-id or embed tarka.rule_content_id in signals".into(),
        ));
    }

    let registry_url = cfg.registry_url.as_ref().ok_or_else(|| {
        CliError::RuleResolution(
            "batch-replay requires --registry-url (or TARKA_REGISTRY_URL) or --rule-json".into(),
        )
    })?;

    for content_id in content_ids {
        if catalog.contains_key(content_id) {
            continue;
        }
        validate_content_id_hex(content_id)?;
        let rr = registry::fetch_rule_by_content_hash(
            &http,
            registry_url,
            content_id,
            cfg.http_timeout,
            cfg.http_retries,
        )
        .await?;
        if let Some(h) = rr.content_hash.as_ref() {
            let hl = h.trim().to_lowercase();
            if !hl.is_empty() && hl != *content_id {
                return Err(CliError::RuleResolution(format!(
                    "registry content_hash {hl} does not match requested id {content_id}"
                )));
            }
        }
        catalog.insert(content_id.clone(), rr.rule_body.into_bytes().into());
    }

    Ok(Arc::new(catalog))
}

fn resolve_content_id_for_manifest(
    manifest: &EvidenceManifest,
    forced: Option<&str>,
) -> Result<String, CliError> {
    if let Some(id) = forced {
        let token = id.trim().to_lowercase();
        if token.is_empty() {
            return Err(CliError::RuleResolution(
                "forced rule content id must be non-empty".into(),
            ));
        }
        return Ok(token);
    }
    let signals = signals_map_from_manifest(manifest);
    embedded_rule_content_id(&signals).ok_or_else(|| {
        CliError::RuleResolution(
            "manifest missing tarka.rule_content_id signal; pass --rule-content-id".into(),
        )
    })
}

fn signals_map_from_manifest(manifest: &EvidenceManifest) -> serde_json::Map<String, Value> {
    let mut map = serde_json::Map::new();
    let Some(input) = manifest.input_map.as_ref() else {
        return map;
    };
    for (key, value) in &input.entries {
        map.insert(key.clone(), signal_value_to_json(value));
    }
    map
}

fn signal_value_to_json(value: &SignalValue) -> Value {
    use tarka_core::evidence::signal_value::Value as Scalar;
    match &value.value {
        Some(Scalar::BoolValue(v)) => Value::Bool(*v),
        Some(Scalar::IntValue(v)) => Value::Number((*v).into()),
        Some(Scalar::DoubleValue(v)) => serde_json::Number::from_f64(*v)
            .map(Value::Number)
            .unwrap_or(Value::Null),
        Some(Scalar::StringValue(v)) => Value::String(v.clone()),
        Some(Scalar::BytesValue(v)) => Value::String(hex::encode(v)),
        None => Value::Null,
    }
}

fn manifest_uuid_from_header(manifest: &EvidenceManifest) -> Result<Uuid, CliError> {
    let header = manifest
        .header
        .as_ref()
        .ok_or_else(|| CliError::BatchReplay("manifest missing header".into()))?;
    let bytes = header.manifest_id.as_slice();
    if bytes.len() != 16 {
        return Err(CliError::BatchReplay(format!(
            "manifest_id must be 16 raw UUID bytes, got {}",
            bytes.len()
        )));
    }
    let arr: [u8; 16] = bytes
        .try_into()
        .map_err(|_| CliError::BatchReplay("manifest_id byte conversion failed".into()))?;
    Ok(Uuid::from_bytes(arr))
}

fn steps_to_trace_json(steps: &[Step]) -> Vec<TraceStepJson> {
    let mut out = Vec::with_capacity(steps.len());
    out.extend(steps.iter().map(|step| TraceStepJson {
        rule_id: step.rule_id.clone(),
        logic_operator: step.logic_operator.clone(),
        operands: step.operands.clone(),
        result: step.result,
        state_snapshot: step.state_snapshot.clone(),
        otel_trace_id: step.otel_trace_id.clone(),
    }));
    out
}

fn trace_steps_equivalent(original: &[Step], replay: &[Step], compare_otel: bool) -> bool {
    if original.len() != replay.len() {
        return false;
    }
    for (left, right) in original.iter().zip(replay.iter()) {
        if left.rule_id != right.rule_id
            || left.logic_operator != right.logic_operator
            || left.result != right.result
            || left.operands != right.operands
            || left.state_snapshot != right.state_snapshot
        {
            return false;
        }
        if compare_otel && left.otel_trace_id != right.otel_trace_id {
            return false;
        }
    }
    true
}

pub fn parse_rfc3339_to_unix_ns(raw: &str, flag: &'static str) -> Result<i64, CliError> {
    let token = raw.trim();
    if token.is_empty() {
        eprint_batch_replay_field_error(flag, "must be a non-empty RFC3339 datetime string");
        return Err(CliError::BatchReplayField {
            flag,
            message: "value is empty".into(),
        });
    }

    let parsed = chrono::DateTime::parse_from_rfc3339(token).map_err(|e| {
        eprint_batch_replay_field_error(
            flag,
            &format!("must be a valid RFC3339 datetime (parse error: {e})"),
        );
        CliError::BatchReplayField {
            flag,
            message: e.to_string(),
        }
    })?;

    parsed.timestamp_nanos_opt().ok_or_else(|| {
        eprint_batch_replay_field_error(flag, "datetime is out of range for unix nanoseconds");
        CliError::BatchReplayField {
            flag,
            message: "timestamp out of range".into(),
        }
    })
}

pub fn eprint_batch_replay_field_error(flag: &str, detail: &str) {
    eprintln!("batch-replay error: flag {flag} {detail}");
    eprintln!("required flags:");
    eprintln!("  --since <RFC3339>       inclusive window start");
    eprintln!("  --until <RFC3339>       inclusive window end");
    eprintln!("  --tenant <string>       tenant_id filter for ClickHouse row policy + query");
    eprintln!("optional flags:");
    eprintln!("  --scorecard-output <path>  write ReplayScorecard JSON (stdout fallback if unwritable)");
    eprintln!("  --concurrency <N>       parallel replay workers (default: CPU core count)");
}

/// Fetch a tenant-scoped batch of [`EvidenceManifest`] rows from ClickHouse for deterministic replay.
pub async fn fetch_manifest_batch_by_window(
    ch_client: &ClickhouseClient,
    start_ts: i64,
    end_ts: i64,
    tenant_id: &str,
) -> Result<Vec<EvidenceManifest>, TarkaCoreError> {
    validate_window_bounds(start_ts, end_ts)?;
    if tenant_id.trim().is_empty() {
        return Err(TarkaCoreError::EmptyTenantId);
    }

    let rows = ch_client
        .fetch_manifest_rows_by_window(start_ts, end_ts, tenant_id)
        .await
        .map_err(cli_error_to_core)?;

  rows_to_evidence_manifests(&rows)
}

fn validate_window_bounds(start_ts: i64, end_ts: i64) -> Result<(), TarkaCoreError> {
    if start_ts < 0 {
        return Err(TarkaCoreError::NegativeWindowStart(start_ts));
    }
    if start_ts > end_ts {
        return Err(TarkaCoreError::InvalidWindow {
            start: start_ts,
            end: end_ts,
        });
    }
    Ok(())
}

fn cli_error_to_core(err: CliError) -> TarkaCoreError {
    match err {
        CliError::ClickHousePayload { reason } if reason.contains("exceeding memory-safe cap") => {
            let cap = clickhouse::MAX_MANIFEST_BATCH_WINDOW_PULL;
            TarkaCoreError::BatchWindowCapExceeded {
                count: cap + 1,
                cap,
            }
        }
        other => TarkaCoreError::ClickHouse(other.to_string()),
    }
}

fn row_to_evidence_manifest(row: &EvidenceManifestRow) -> Result<EvidenceManifest, TarkaCoreError> {
    evidence_manifest_from_clickhouse_row_impl(row)
}

/// Convert a ClickHouse JSON row into the protobuf replay envelope (test / harness helper).
#[cfg(feature = "test-helpers")]
pub fn evidence_manifest_from_clickhouse_row(
    row: &EvidenceManifestRow,
) -> Result<EvidenceManifest, TarkaCoreError> {
    evidence_manifest_from_clickhouse_row_impl(row)
}

fn evidence_manifest_from_clickhouse_row_impl(
    row: &EvidenceManifestRow,
) -> Result<EvidenceManifest, TarkaCoreError> {
    let manifest_uuid = Uuid::parse_str(row.manifest_id.trim()).map_err(|e| {
        TarkaCoreError::InvalidManifestId(format!("{} ({e})", row.manifest_id))
    })?;

    let steps = proto_steps_from_manifest_row(row)?;
    let mut entries = BTreeMap::new();
    for (key, raw) in &row.signals {
        let normalized = normalize_signal_value(raw);
        entries.insert(key.clone(), json_value_to_signal_value(&normalized));
    }

    let signature = hex::decode(row.crypto_signature_hex.trim()).unwrap_or_default();

    Ok(EvidenceManifest {
        header: Some(Header {
            manifest_id: manifest_uuid.as_bytes().to_vec(),
            engine_version: row.engine_version.clone(),
            timestamp_ns: row.timestamp_ns,
            engine_fingerprint: String::new(),
        }),
        input_map: Some(InputMap { entries }),
        trace: Some(Trace { steps }),
        metadata: Some(Metadata {
            final_decision: row.final_decision != 0,
            total_execution_time_us: row.total_execution_time_us,
        }),
        crypto_signature: Some(CryptoSignature {
            algorithm: row.crypto_algorithm.clone(),
            signature,
            key_id: row.crypto_key_id.clone(),
        }),
    })
}

fn json_value_to_signal_value(value: &Value) -> SignalValue {
    let scalar = match value {
        Value::Bool(b) => SignalScalar::BoolValue(*b),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                SignalScalar::IntValue(i)
            } else if let Some(f) = n.as_f64() {
                SignalScalar::DoubleValue(f)
            } else {
                SignalScalar::StringValue(n.to_string())
            }
        }
        Value::String(s) => SignalScalar::StringValue(s.clone()),
        Value::Null => SignalScalar::StringValue(String::new()),
        other => SignalScalar::StringValue(other.to_string()),
    };
    SignalValue {
        value: Some(scalar),
    }
}

fn proto_steps_from_manifest_row(row: &EvidenceManifestRow) -> Result<Vec<Step>, TarkaCoreError> {
    let ch_steps = parse_trace_steps(row).map_err(|e| TarkaCoreError::ManifestDecode(e.to_string()))?;
    Ok(trace_json_to_proto_steps(&ch_steps))
}

#[cfg(test)]
mod batch_window_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn execute_batch_replay_parallel_empty_input() {
        let ctx = Arc::new(BatchReplayExecutionContext {
            concurrency: 2,
            forced_content_id: None,
            rules: Arc::new(HashMap::new()),
            wasm_modules: None,
            strict_timing: false,
            compare_otel: false,
            ground_truth_labels: Arc::new(HashMap::new()),
        });
        let collector = execute_batch_replay_parallel(Vec::new(), ctx);
        assert_eq!(collector.counters().manifests_consumed, 0);
        assert_eq!(collector.counters().total_evaluated, 0);
    }

    #[test]
    fn validate_window_bounds_rejects_inverted_range() {
        let err = validate_window_bounds(100, 50).unwrap_err();
        assert_eq!(
            err,
            TarkaCoreError::InvalidWindow {
                start: 100,
                end: 50
            }
        );
    }

    #[test]
    fn validate_window_bounds_rejects_negative_start() {
        let err = validate_window_bounds(-1, 10).unwrap_err();
        assert_eq!(err, TarkaCoreError::NegativeWindowStart(-1));
    }

    #[test]
    fn row_to_evidence_manifest_maps_clickhouse_row() {
        let row = EvidenceManifestRow {
            tenant_id: "tenant-a".into(),
            manifest_id: "550e8400-e29b-41d4-a716-446655440000".into(),
            engine_version: "0.1.0".into(),
            timestamp_ns: 1_700_000_000_000_000_000,
            final_decision: 1,
            total_execution_time_us: 42,
            signals: serde_json::Map::from_iter([("amount".into(), json!("1250"))]),
            trace_json: json!([{
                "rule_id": "velocity_ip",
                "logic_operator": "AND",
                "operands": ["amount"],
                "result": true,
                "state_snapshot": {"amount": "1250"},
                "otel_trace_id": ""
            }]),
            crypto_algorithm: "Ed25519ph".into(),
            crypto_signature_hex: "aa".repeat(64),
            crypto_key_id: "local-dev".into(),
            raw_manifest_sha256: None,
        };

        let manifest = row_to_evidence_manifest(&row).expect("convert row");
        let header = manifest.header.expect("header");
        assert_eq!(header.engine_version, "0.1.0");
        assert_eq!(header.timestamp_ns, 1_700_000_000_000_000_000);
        let metadata = manifest.metadata.expect("metadata");
        assert!(metadata.final_decision);
        assert_eq!(metadata.total_execution_time_us, 42);
        let trace = manifest.trace.expect("trace");
        assert_eq!(trace.steps.len(), 1);
        assert_eq!(trace.steps[0].rule_id, "velocity_ip");
        let input = manifest.input_map.expect("input_map");
        assert!(input.entries.contains_key("amount"));
    }
}

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
    let mut out = Vec::with_capacity(steps.len());
    out.extend(steps.iter().map(|s| {
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
    }));
    out
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
