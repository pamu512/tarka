//! Native integration tests for ``tarka batch-replay`` CLI execution paths.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

use serde_json::Value;
use tarka_cli::parse_rfc3339_to_unix_ns;
use tarka_cli::test_helpers::{
    ManifestTestVectorBuilder, MockClickHouseHarness, TraceStepSpec,
};
use tarka_core::rule_content_sha256;
use tempfile::TempDir;

const WINDOW_SINCE: &str = "2026-05-01T00:00:00Z";
const WINDOW_UNTIL: &str = "2026-05-01T23:59:59Z";
const TEST_TENANT: &str = "batch-replay-itest";

fn tarka_bin() -> PathBuf {
    std::env::var("CARGO_BIN_EXE_tarka")
        .map(PathBuf::from)
        .expect("CARGO_BIN_EXE_tarka must be set for integration tests")
}

fn rule_content_id_hex(rule_json: &str) -> String {
    hex::encode(rule_content_sha256(rule_json.as_bytes()))
}

fn write_rule_json(dir: &Path, threshold: f64, rule_id: &str) -> (PathBuf, String) {
    let rule_json = format!(
        r#"{{"kind":"compare_leaf","id":"{rule_id}","path":"/amount","op":"gt","expected":{threshold}}}"#
    );
    let content_id = rule_content_id_hex(&rule_json);
    let path = dir.join(format!("{rule_id}.json"));
    fs::write(&path, &rule_json).expect("write rule json");
    (path, content_id)
}

fn window_timestamp_ns(offset_ns: i64) -> u64 {
    let since_ns = parse_rfc3339_to_unix_ns(WINDOW_SINCE, "--since").expect("since parse");
    (since_ns + offset_ns) as u64
}

fn run_batch_replay(
    mock_base_url: &str,
    tenant: &str,
    scorecard_path: &Path,
    rule_json: Option<(&Path, &str)>,
) -> Output {
    let mut cmd = Command::new(tarka_bin());
    cmd.args([
        "batch-replay",
        "--since",
        WINDOW_SINCE,
        "--until",
        WINDOW_UNTIL,
        "--tenant",
        tenant,
        "--clickhouse-url",
        mock_base_url,
        "--clickhouse-database",
        "tarka_audit",
        "--clickhouse-table",
        "evidence_manifests",
        "--scorecard-output",
        scorecard_path.to_str().expect("scorecard path utf-8"),
        "--concurrency",
        "2",
        "--max-false-positive-rate-delta",
        "0.0005",
    ])
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());

    if let Some((path, content_id)) = rule_json {
        cmd.args([
            "--rule-json",
            path.to_str().expect("rule path utf-8"),
            "--rule-content-id",
            content_id,
        ]);
    }

    cmd.output().expect("spawn tarka batch-replay")
}

fn read_scorecard(path: &Path) -> Value {
    let raw = fs::read_to_string(path).expect("read scorecard json");
    serde_json::from_str(&raw).expect("parse scorecard json")
}

#[tokio::test]
async fn batch_replay_empty_window_exits_success_with_zero_processed() {
    let harness = MockClickHouseHarness::spawn().await;
    let tmp = TempDir::new().expect("tempdir");
    let scorecard_path = tmp.path().join("empty_scorecard.json");

    let output = run_batch_replay(&harness.base_url(), TEST_TENANT, &scorecard_path, None);

    assert!(
        output.status.success(),
        "expected exit 0 for empty window; stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );

    let scorecard = read_scorecard(&scorecard_path);
    assert_eq!(scorecard.get("total_evaluated").and_then(|v| v.as_u64()), Some(0));
    assert_eq!(
        scorecard.get("decision_match_count").and_then(|v| v.as_u64()),
        Some(0)
    );
    assert_eq!(
        scorecard.get("mismatches")
            .and_then(|v| v.as_array())
            .map(|a| a.len()),
        Some(0)
    );
}

#[tokio::test]
async fn batch_replay_rule_mismatch_exits_failure_and_records_scorecard_delta() {
    let harness = MockClickHouseHarness::spawn().await;

    // Historical audit captured ALLOW (amount 1250 vs threshold 5000 in trace).
    let vector = ManifestTestVectorBuilder::new()
        .tenant_id(TEST_TENANT)
        .timestamp_ns(window_timestamp_ns(3_600_000_000_000)) // +1h within window
        .amount(1_250.0)
        .final_decision(false)
        .trace_steps(vec![TraceStepSpec {
            rule_id: "audit.amount_gt".into(),
            logic_operator: "COMPARE".into(),
            operands: vec!["amount".into(), "threshold".into()],
            result: false,
            state_snapshot: [
                ("amount".into(), "1250".into()),
                ("compare.threshold".into(), "5000".into()),
            ]
            .into_iter()
            .collect(),
            otel_trace_id: String::new(),
        }])
        .build()
        .expect("build manifest vector");
    harness.seed_vector(&vector);

    let tmp = TempDir::new().expect("tempdir");
    let (rule_path, content_id) = write_rule_json(tmp.path(), 1_000.0, "replay.amount_gt");
    let scorecard_path = tmp.path().join("mismatch_scorecard.json");

  // Replay engine uses a stricter rule (amount > 1000) than the historical audit log.
    let output = run_batch_replay(
        &harness.base_url(),
        TEST_TENANT,
        &scorecard_path,
        Some((&rule_path, &content_id)),
    );

    assert!(
        !output.status.success(),
        "expected exit 1 when replay diverges from audit; stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        output.status.code(),
        Some(1),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );

    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("batch-replay performance gate FAILED"),
        "expected performance gate failure message; stderr={stderr}"
    );

    let scorecard = read_scorecard(&scorecard_path);
    let total = scorecard
        .get("total_evaluated")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    assert_eq!(total, 1, "scorecard: {scorecard}");

    let decision_matches = scorecard
        .get("decision_match_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    assert_eq!(decision_matches, 0);

    let mismatches = scorecard
        .get("mismatches")
        .and_then(|v| v.as_array())
        .expect("mismatches array");
    assert_eq!(mismatches.len(), 1);

    let mismatch = &mismatches[0];
    assert_eq!(
        mismatch.get("historical_decision").and_then(|v| v.as_bool()),
        Some(false)
    );
    assert_eq!(
        mismatch.get("new_decision").and_then(|v| v.as_bool()),
        Some(true)
    );
    assert!(
        mismatch
            .get("diverged_rules")
            .and_then(|v| v.as_array())
            .is_some_and(|rules| !rules.is_empty()),
        "expected diverged_rules in mismatch detail"
    );
}
