//! `tarka` operator CLI entrypoint.

use std::collections::BTreeSet;
use std::env;
use std::path::PathBuf;
use std::process::{ExitCode, exit};
use std::time::Duration;

use clap::{Parser, Subcommand};
use uuid::Uuid;

use tarka_cli::{
    parse_rfc3339_to_unix_ns, run_batch_replay, run_forensic_replay, BatchReplayConfig, CliError,
    ForensicReplayConfig, ReplayScorecard,
};

#[derive(Parser)]
#[command(name = "tarka")]
#[command(
    about = "Tarka operator CLI — forensic evidence replay, operational tooling",
    version,
    propagate_version = true
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Fetch an EvidenceManifest row from ClickHouse, load the immutable rule from a registry (or local JSON),
    /// re-evaluate with deterministic clock / reconstructed externals, and print a diff vs captured audit state.
    Replay(ReplayArgs),
    /// Pull a tenant-scoped manifest window from ClickHouse and emit a batch replay scorecard.
    #[command(name = "batch-replay")]
    BatchReplay(BatchReplayArgs),
}

#[derive(clap::Args, Clone, Debug)]
struct ClickHouseHttpArgs {
    /// ClickHouse HTTP endpoint (`http://host:8123`).
    #[arg(long, env = "CLICKHOUSE_HTTP_URL", default_value = "http://127.0.0.1:8123")]
    clickhouse_url: String,

    #[arg(long, env = "CLICKHOUSE_DATABASE", default_value = "tarka_audit")]
    clickhouse_database: String,

    #[arg(long, env = "CLICKHOUSE_TABLE", default_value = "evidence_manifests")]
    clickhouse_table: String,

    /// ClickHouse mirror table for active ``normalized_labels`` ground-truth rows.
    #[arg(
        long,
        env = "CLICKHOUSE_NORMALIZED_LABELS_TABLE",
        default_value = "normalized_labels"
    )]
    normalized_labels_table: String,

    #[arg(long, env = "CLICKHOUSE_USER", default_value = "default")]
    clickhouse_user: String,

    #[arg(long, env = "CLICKHOUSE_PASSWORD", default_value = "")]
    clickhouse_password: String,

    /// Session tenant for ClickHouse row policies (`SET tarka_tenant_id`); HTTP query parameter when set.
    #[arg(long, env = "CLICKHOUSE_ROW_POLICY_TENANT_ID")]
    clickhouse_row_policy_tenant_id: Option<String>,
}

#[derive(Parser)]
struct ReplayArgs {
    /// Evidence manifest UUID (matches ClickHouse `manifest_id` and protobuf `Header.manifest_id`).
    manifest_id: Uuid,

    #[command(flatten)]
    clickhouse: ClickHouseHttpArgs,

    /// Base URL for the immutable rule registry (see `GET /v1/registry/rules/by-content-hash/{hex}`).
    #[arg(long, env = "TARKA_REGISTRY_URL")]
    registry_url: Option<String>,

    /// Local path to the exact UTF-8 rule JSON bytes (alternative to `--registry-url`).
    #[arg(long)]
    rule_json: Option<PathBuf>,

    /// Lowercase hex SHA-256 of the rule JSON (required unless `tarka.rule_content_id` exists in ClickHouse signals).
    #[arg(long, env = "TARKA_RULE_CONTENT_ID")]
    rule_content_id: Option<String>,

    #[arg(long, default_value_t = 45)]
    http_timeout_secs: u64,

    #[arg(long, default_value_t = 3)]
    http_retries: u32,

    /// Directory containing `<sha256-hex>.wasm` artifacts for `WasmCustomLeaf` replay.
    #[arg(long)]
    wasm_dir: Option<PathBuf>,

    /// Fail the diff when `total_execution_time_us` differs (normally informational noise).
    #[arg(long, default_value_t = false)]
    strict_timing: bool,

    /// Compare OpenTelemetry trace ids on leaf steps (often differs across hosts).
    #[arg(long, default_value_t = false)]
    compare_otel: bool,
}

#[derive(Parser)]
struct BatchReplayArgs {
    /// Inclusive window start (RFC3339 datetime, e.g. `2026-05-01T00:00:00Z`).
    #[arg(
        long,
        required = true,
        help = "Inclusive replay window start (RFC3339 datetime)"
    )]
    since: String,

    /// Inclusive window end (RFC3339 datetime).
    #[arg(
        long,
        required = true,
        help = "Inclusive replay window end (RFC3339 datetime)"
    )]
    until: String,

    /// Tenant id filter applied to ClickHouse queries and row-level security session settings.
    #[arg(long, required = true, help = "Tenant id filter for the manifest batch pull")]
    tenant: String,

    /// Parallel replay worker count (defaults to the host CPU core count).
    #[arg(long, default_value_t = default_concurrency(), help = "Parallel replay worker count")]
    concurrency: usize,

    /// Destination path for the JSON batch replay scorecard artifact.
    #[arg(
        long,
        value_name = "PATH",
        help = "Write ReplayScorecard JSON to this path (fallback to stdout if unwritable)"
    )]
    scorecard_output: Option<PathBuf>,

    #[command(flatten)]
    clickhouse: ClickHouseHttpArgs,

    #[arg(long, default_value_t = 45)]
    http_timeout_secs: u64,

    #[arg(long, default_value_t = 3)]
    http_retries: u32,

    /// Base URL for the immutable rule registry (see `GET /v1/registry/rules/by-content-hash/{hex}`).
    #[arg(long, env = "TARKA_REGISTRY_URL")]
    registry_url: Option<String>,

    /// Local path to the exact UTF-8 rule JSON bytes (alternative to `--registry-url`).
    #[arg(long)]
    rule_json: Option<PathBuf>,

    /// Lowercase hex SHA-256 of the rule JSON (required unless `tarka.rule_content_id` exists in manifest signals).
    #[arg(long, env = "TARKA_RULE_CONTENT_ID")]
    rule_content_id: Option<String>,

    /// Directory containing `<sha256-hex>.wasm` artifacts for `WasmCustomLeaf` replay.
    #[arg(long)]
    wasm_dir: Option<PathBuf>,

    /// Fail the diff when `total_execution_time_us` differs (normally informational noise).
    #[arg(long, default_value_t = false)]
    strict_timing: bool,

    /// Compare OpenTelemetry trace ids on leaf steps (often differs across hosts).
    #[arg(long, default_value_t = false)]
    compare_otel: bool,

    /// Maximum allowed replay false-positive-rate degradation vs historical baseline.
    #[arg(
        long,
        env = "TARKA_MAX_FALSE_POSITIVE_RATE_DELTA",
        default_value_t = default_max_false_positive_rate_delta(),
        help = "Fail when false_positive_rate_delta exceeds this value (default: 0.0005)"
    )]
    max_false_positive_rate_delta: f64,
}

fn default_concurrency() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
        .max(1)
}

fn default_max_false_positive_rate_delta() -> f64 {
    0.0005
}

/// Strict batch replay performance gates (100% parity + bounded FPR degradation).
#[derive(Debug, Clone, Copy, PartialEq)]
struct PerformanceThresholds {
    max_false_positive_rate_delta: f64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PerformanceGateReport {
    violations: Vec<String>,
    offending_rules: Vec<String>,
}

impl PerformanceGateReport {
    fn passed(&self) -> bool {
        self.violations.is_empty()
    }
}

fn parse_performance_thresholds(max_false_positive_rate_delta: f64) -> Result<PerformanceThresholds, CliError> {
    if !max_false_positive_rate_delta.is_finite() {
        tarka_cli::eprint_batch_replay_field_error(
            "--max-false-positive-rate-delta",
            "must be a finite number",
        );
        return Err(CliError::BatchReplayField {
            flag: "--max-false-positive-rate-delta",
            message: "value is not finite".into(),
        });
    }
    if max_false_positive_rate_delta < 0.0 {
        tarka_cli::eprint_batch_replay_field_error(
            "--max-false-positive-rate-delta",
            "must be >= 0",
        );
        return Err(CliError::BatchReplayField {
            flag: "--max-false-positive-rate-delta",
            message: "value is negative".into(),
        });
    }
    Ok(PerformanceThresholds {
        max_false_positive_rate_delta,
    })
}

fn evaluate_performance_thresholds(
    replay: &ReplayScorecard,
    thresholds: &PerformanceThresholds,
) -> PerformanceGateReport {
    let mut violations = Vec::new();

    if replay.total_evaluated == 0 {
        // Empty tenant/window: success with zero manifests — no parity rates to assert.
    } else {
        let decision_match_rate =
            replay.decision_match_count as f64 / replay.total_evaluated as f64;
        if decision_match_rate < 1.0 {
            violations.push(format!(
                "decision_match_rate={decision_match_rate:.6} < 1.000000 (100%)"
            ));
        }

        let step_parity_rate = replay.step_parity_count as f64 / replay.total_evaluated as f64;
        if step_parity_rate < 1.0 {
            violations.push(format!(
                "step_parity_rate={step_parity_rate:.6} < 1.000000 (100%)"
            ));
        }
    }

    if replay.false_positive_rate_delta > thresholds.max_false_positive_rate_delta {
        violations.push(format!(
            "false_positive_rate_delta={:.6} > max_allowed={:.6}",
            replay.false_positive_rate_delta, thresholds.max_false_positive_rate_delta
        ));
    }

    let mut offending_rules = BTreeSet::new();
    for mismatch in &replay.mismatches {
        for rule_id in &mismatch.diverged_rules {
            let token = rule_id.trim();
            if !token.is_empty() {
                offending_rules.insert(token.to_string());
            }
        }
    }

    PerformanceGateReport {
        violations,
        offending_rules: offending_rules.into_iter().collect(),
    }
}

fn enforce_performance_thresholds(replay: &ReplayScorecard, thresholds: &PerformanceThresholds) {
    let report = evaluate_performance_thresholds(replay, thresholds);
    if report.passed() {
        return;
    }

    eprintln!("batch-replay performance gate FAILED:");
    for violation in &report.violations {
        eprintln!("  - {violation}");
    }
    if report.offending_rules.is_empty() {
        eprintln!("offending rules: (none identified in mismatch diverged_rules)");
    } else {
        eprintln!("offending rules:");
        for rule_id in &report.offending_rules {
            eprintln!("  - {rule_id}");
        }
    }
    exit(1);
}

#[tokio::main]
async fn main() -> ExitCode {
    let _ = tarka_core::tracing_elk::try_install_elk_json_tracing();
    let cli = Cli::parse();
    match run(cli).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            tracing::error!(error = %e, "tarka_cli_failed");
            exit_code_for_error(&e)
        }
    }
}

async fn run(cli: Cli) -> Result<(), CliError> {
    match cli.command {
        Commands::Replay(args) => {
            let trace_id =
                env::var("TARKA_TRACE_ID").unwrap_or_else(|_| Uuid::new_v4().simple().to_string());
            let rule_set_hash = env::var("TARKA_RULE_SET_HASH").unwrap_or_default();
            let tenant_id = env::var("TARKA_TENANT_ID").unwrap_or_default();
            let _replay_span = tracing::info_span!(
                "tarka_cli_replay",
                trace_id = %trace_id,
                rule_set_hash = %rule_set_hash,
                tenant_id = %tenant_id
            )
            .entered();

            let cfg = ForensicReplayConfig {
                manifest_id: args.manifest_id,
                clickhouse_url: args.clickhouse.clickhouse_url,
                clickhouse_database: args.clickhouse.clickhouse_database,
                clickhouse_table: args.clickhouse.clickhouse_table,
                clickhouse_user: args.clickhouse.clickhouse_user,
                clickhouse_password: args.clickhouse.clickhouse_password,
                clickhouse_row_policy_tenant_id: args.clickhouse.clickhouse_row_policy_tenant_id,
                registry_url: args.registry_url,
                rule_json_path: args.rule_json,
                rule_content_id: args.rule_content_id,
                http_timeout: Duration::from_secs(args.http_timeout_secs),
                http_retries: args.http_retries,
                wasm_dir: args.wasm_dir,
                strict_timing: args.strict_timing,
                compare_otel: args.compare_otel,
            };
            let report = run_forensic_replay(cfg).await?;
            print!("{report}");
            Ok(())
        }
        Commands::BatchReplay(args) => {
            let scorecard_output = args.scorecard_output.clone();
            let thresholds = parse_performance_thresholds(args.max_false_positive_rate_delta)?;
            let cfg = build_batch_replay_config(args)?;
            let replay = run_batch_replay(cfg).await?;
            if let Some(path) = scorecard_output {
                write_replay_scorecard_or_fallback(&replay, &path)?;
            }
            enforce_performance_thresholds(&replay, &thresholds);
            Ok(())
        }
    }
}

fn build_batch_replay_config(args: BatchReplayArgs) -> Result<BatchReplayConfig, CliError> {
    let tenant = args.tenant.trim();
    if tenant.is_empty() {
        tarka_cli::eprint_batch_replay_field_error("--tenant", "must be a non-empty string");
        return Err(CliError::BatchReplayField {
            flag: "--tenant",
            message: "value is empty".into(),
        });
    }

    if let Some(path) = &args.scorecard_output {
        if path.as_os_str().is_empty() {
            tarka_cli::eprint_batch_replay_field_error(
                "--scorecard-output",
                "must be a non-empty filesystem path when provided",
            );
            return Err(CliError::BatchReplayField {
                flag: "--scorecard-output",
                message: "path is empty".into(),
            });
        }
    }

    if args.concurrency == 0 {
        tarka_cli::eprint_batch_replay_field_error("--concurrency", "must be a positive integer");
        return Err(CliError::BatchReplayField {
            flag: "--concurrency",
            message: "must be >= 1".into(),
        });
    }

    let since_unix_ns = parse_rfc3339_to_unix_ns(&args.since, "--since")?;
    let until_unix_ns = parse_rfc3339_to_unix_ns(&args.until, "--until")?;
    if since_unix_ns > until_unix_ns {
        eprintln!(
            "batch-replay error: --since ({}) must be <= --until ({})",
            args.since.trim(),
            args.until.trim()
        );
        return Err(CliError::BatchReplayField {
            flag: "--since",
            message: format!(
                "window start {} is after window end {}",
                args.since.trim(),
                args.until.trim()
            ),
        });
    }

    Ok(BatchReplayConfig {
        since_rfc3339: args.since.trim().to_string(),
        until_rfc3339: args.until.trim().to_string(),
        since_unix_ns,
        until_unix_ns,
        tenant_id: tenant.to_string(),
        concurrency: args.concurrency,
        clickhouse_url: args.clickhouse.clickhouse_url,
        clickhouse_database: args.clickhouse.clickhouse_database,
        clickhouse_table: args.clickhouse.clickhouse_table,
        clickhouse_user: args.clickhouse.clickhouse_user,
        clickhouse_password: args.clickhouse.clickhouse_password,
        normalized_labels_table: args.clickhouse.normalized_labels_table,
        http_timeout: Duration::from_secs(args.http_timeout_secs),
        http_retries: args.http_retries,
        registry_url: args.registry_url,
        rule_json_path: args.rule_json,
        rule_content_id: args.rule_content_id,
        wasm_dir: args.wasm_dir,
        strict_timing: args.strict_timing,
        compare_otel: args.compare_otel,
    })
}

fn write_replay_scorecard_or_fallback(
    replay: &ReplayScorecard,
    path: &PathBuf,
) -> Result<(), CliError> {
    let body = replay.to_json_pretty().map_err(|e| {
        CliError::BatchReplay(format!("encode scorecard JSON: {e}"))
    })?;

    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            if let Err(source) = std::fs::create_dir_all(parent) {
                emit_scorecard_fallback_trace(path, &source, &body);
                return Err(CliError::ScorecardWrite {
                    path: path.clone(),
                    source,
                });
            }
        }
    }

    match std::fs::write(path, &body) {
        Ok(()) => Ok(()),
        Err(source) => {
            emit_scorecard_fallback_trace(path, &source, &body);
            Err(CliError::ScorecardWrite {
                path: path.clone(),
                source,
            })
        }
    }
}

fn emit_scorecard_fallback_trace(path: &PathBuf, source: &std::io::Error, body: &str) {
    eprintln!(
        "batch-replay: unable to write scorecard to {} ({source}); emitting JSON fallback to stdout",
        path.display()
    );
    println!("{body}");
}

fn exit_code_for_error(err: &CliError) -> ExitCode {
    match err {
        CliError::ManifestNotFound(_) => ExitCode::from(4),
        CliError::RuleResolution(_) => ExitCode::from(5),
        CliError::PartialReplay { .. } => ExitCode::from(6),
        CliError::WasmMissing(_) => ExitCode::from(7),
        CliError::BatchReplayField { .. } => ExitCode::from(2),
        CliError::BatchReplay(_) | CliError::ScorecardWrite { .. } => ExitCode::from(1),
        _ => ExitCode::from(1),
    }
}

#[cfg(test)]
mod performance_gate_tests {
    use super::*;
    use tarka_cli::MismatchDetail;

    fn scorecard(
        total: u64,
        decision_matches: u64,
        step_parity: u64,
        fpr_delta: f64,
        mismatches: Vec<MismatchDetail>,
    ) -> ReplayScorecard {
        ReplayScorecard {
            total_evaluated: total,
            decision_match_count: decision_matches,
            step_parity_count: step_parity,
            mismatches,
            false_positive_rate_delta: fpr_delta,
            precision_delta: 0.0,
            recall_delta: 0.0,
            execution_time_ms: 1,
            transactions_per_second: 0.0,
        }
    }

    #[test]
    fn parse_performance_thresholds_rejects_negative_delta() {
        let err = parse_performance_thresholds(-0.1).unwrap_err();
        assert!(matches!(err, CliError::BatchReplayField { .. }));
    }

    #[test]
    fn evaluate_passes_for_empty_window_with_zero_evaluated() {
        let report = evaluate_performance_thresholds(
            &scorecard(0, 0, 0, 0.0, Vec::new()),
            &PerformanceThresholds {
                max_false_positive_rate_delta: 0.0005,
            },
        );
        assert!(report.passed());
        assert!(report.violations.is_empty());
    }

    #[test]
    fn evaluate_flags_subperfect_decision_match_rate() {
        let report = evaluate_performance_thresholds(
            &scorecard(2, 1, 2, 0.0, Vec::new()),
            &PerformanceThresholds {
                max_false_positive_rate_delta: 0.0005,
            },
        );
        assert!(!report.passed());
        assert!(report.violations.iter().any(|v| v.contains("decision_match_rate")));
    }

    #[test]
    fn evaluate_flags_fpr_delta_above_threshold() {
        let report = evaluate_performance_thresholds(
            &scorecard(1, 1, 1, 0.001, Vec::new()),
            &PerformanceThresholds {
                max_false_positive_rate_delta: 0.0005,
            },
        );
        assert!(!report.passed());
        assert!(report
            .violations
            .iter()
            .any(|v| v.contains("false_positive_rate_delta")));
    }

    #[test]
    fn evaluate_collects_offending_rules_from_mismatches() {
        let report = evaluate_performance_thresholds(
            &scorecard(
                1,
                0,
                0,
                0.0,
                vec![MismatchDetail {
                    manifest_id: "m-1".into(),
                    historical_decision: Some(true),
                    new_decision: Some(false),
                    diverged_rules: vec!["velocity_ip".into()],
                    diff_trace: "pivot".into(),
                    error: None,
                }],
            ),
            &PerformanceThresholds {
                max_false_positive_rate_delta: 0.0005,
            },
        );
        assert_eq!(report.offending_rules, vec!["velocity_ip".to_string()]);
    }
}
