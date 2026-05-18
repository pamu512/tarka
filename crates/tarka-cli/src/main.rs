//! `tarka` operator CLI entrypoint.

use std::env;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use clap::{Parser, Subcommand};
use uuid::Uuid;

use tarka_cli::{run_forensic_replay, CliError, ForensicReplayConfig};

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
}

#[derive(Parser)]
struct ReplayArgs {
    /// Evidence manifest UUID (matches ClickHouse `manifest_id` and protobuf `Header.manifest_id`).
    manifest_id: Uuid,

    /// ClickHouse HTTP endpoint (`http://host:8123`).
    #[arg(long, env = "CLICKHOUSE_HTTP_URL", default_value = "http://127.0.0.1:8123")]
    clickhouse_url: String,

    #[arg(long, env = "CLICKHOUSE_DATABASE", default_value = "tarka_audit")]
    clickhouse_database: String,

    #[arg(long, env = "CLICKHOUSE_TABLE", default_value = "evidence_manifests")]
    clickhouse_table: String,

    #[arg(long, env = "CLICKHOUSE_USER", default_value = "default")]
    clickhouse_user: String,

    #[arg(long, env = "CLICKHOUSE_PASSWORD", default_value = "")]
    clickhouse_password: String,

    /// Session tenant for ClickHouse row policies (`SET tarka_tenant_id`); HTTP query parameter when set.
    #[arg(long, env = "CLICKHOUSE_ROW_POLICY_TENANT_ID")]
    clickhouse_row_policy_tenant_id: Option<String>,

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
                clickhouse_url: args.clickhouse_url,
                clickhouse_database: args.clickhouse_database,
                clickhouse_table: args.clickhouse_table,
                clickhouse_user: args.clickhouse_user,
                clickhouse_password: args.clickhouse_password,
                clickhouse_row_policy_tenant_id: args.clickhouse_row_policy_tenant_id,
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
    }
}

fn exit_code_for_error(err: &CliError) -> ExitCode {
    match err {
        CliError::ManifestNotFound(_) => ExitCode::from(4),
        CliError::RuleResolution(_) => ExitCode::from(5),
        CliError::PartialReplay { .. } => ExitCode::from(6),
        CliError::WasmMissing(_) => ExitCode::from(7),
        _ => ExitCode::from(1),
    }
}
