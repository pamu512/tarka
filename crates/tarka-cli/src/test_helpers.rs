//! Localized test vectors and ephemeral mock ClickHouse for replay unit tests.
//!
//! Provides [`ManifestTestVector`] synthesis (ClickHouse JSON row + protobuf envelope + binary bytes)
//! and [`MockClickHouseHarness`] (wiremock HTTP) so replay tests never require a live database.

use std::collections::{BTreeMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use prost::Message;
use serde_json::{json, Value};
use tarka_core::evidence::EvidenceManifest;
use tarka_core::TarkaCoreError;
use uuid::Uuid;
use wiremock::matchers::method;
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

use crate::clickhouse::{ClickhouseClient, EvidenceManifestRow, NormalizedLabelRow};
use crate::error::CliError;
use crate::replay::evidence_manifest_from_clickhouse_row;

/// Default compare-leaf rule content id used by replay integration tests (SHA-256 hex).
pub const DEFAULT_TEST_RULE_CONTENT_ID: &str =
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

/// One fully-linked replay fixture: ClickHouse row, decoded manifest, protobuf bytes.
#[derive(Debug, Clone)]
pub struct ManifestTestVector {
    pub row: EvidenceManifestRow,
    pub manifest: EvidenceManifest,
    pub binary: Vec<u8>,
}

/// Fluent builder for [`ManifestTestVector`].
#[derive(Debug, Clone)]
pub struct ManifestTestVectorBuilder {
    manifest_id: Uuid,
    tenant_id: String,
    engine_version: String,
    timestamp_ns: u64,
    amount: f64,
    final_decision: bool,
    total_execution_time_us: u64,
    transaction_id: Option<String>,
    rule_content_id: Option<String>,
    trace_steps: Vec<TraceStepSpec>,
    crypto_algorithm: String,
    crypto_signature_hex: String,
    crypto_key_id: String,
}

/// Lightweight trace leaf specification for synthetic audit rows.
#[derive(Debug, Clone)]
pub struct TraceStepSpec {
    pub rule_id: String,
    pub logic_operator: String,
    pub operands: Vec<String>,
    pub result: bool,
    pub state_snapshot: BTreeMap<String, String>,
    pub otel_trace_id: String,
}

impl Default for ManifestTestVectorBuilder {
    fn default() -> Self {
        Self {
            manifest_id: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000")
                .expect("valid default uuid"),
            tenant_id: "test-tenant".into(),
            engine_version: "0.1.0".into(),
            timestamp_ns: 1_700_000_000_000_000_000,
            amount: 1_250.0,
            final_decision: false,
            total_execution_time_us: 42,
            transaction_id: Some("tx-default-001".into()),
            rule_content_id: Some(DEFAULT_TEST_RULE_CONTENT_ID.into()),
            trace_steps: vec![TraceStepSpec {
                rule_id: "backtest.amount_gt".into(),
                logic_operator: "COMPARE".into(),
                operands: vec!["amount".into(), "threshold".into()],
                result: false,
                state_snapshot: BTreeMap::from([
                    ("amount".into(), "1250".into()),
                    ("compare.threshold".into(), "5000".into()),
                ]),
                otel_trace_id: String::new(),
            }],
            crypto_algorithm: "Ed25519ph".into(),
            crypto_signature_hex: "aa".repeat(64),
            crypto_key_id: "local-test".into(),
        }
    }
}

impl ManifestTestVectorBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn manifest_id(mut self, id: Uuid) -> Self {
        self.manifest_id = id;
        self
    }

    pub fn tenant_id(mut self, tenant: impl Into<String>) -> Self {
        self.tenant_id = tenant.into();
        self
    }

    pub fn timestamp_ns(mut self, ts: u64) -> Self {
        self.timestamp_ns = ts;
        self
    }

    pub fn amount(mut self, amount: f64) -> Self {
        self.amount = amount;
        self
    }

    pub fn final_decision(mut self, decision: bool) -> Self {
        self.final_decision = decision;
        self
    }

    pub fn transaction_id(mut self, id: impl Into<String>) -> Self {
        self.transaction_id = Some(id.into());
        self
    }

    pub fn rule_content_id(mut self, hex_id: impl Into<String>) -> Self {
        self.rule_content_id = Some(hex_id.into());
        self
    }

    pub fn trace_steps(mut self, steps: Vec<TraceStepSpec>) -> Self {
        self.trace_steps = steps;
        self
    }

    pub fn build(self) -> Result<ManifestTestVector, TarkaCoreError> {
        synthesize_manifest_test_vector(self)
    }
}

/// Synthesize a linked ClickHouse row, protobuf manifest, and encoded binary payload.
pub fn synthesize_manifest_test_vector(
    builder: ManifestTestVectorBuilder,
) -> Result<ManifestTestVector, TarkaCoreError> {
    let row = clickhouse_row_from_builder(&builder);
    let manifest = evidence_manifest_from_clickhouse_row(&row)?;
    let binary = encode_evidence_manifest_binary(&manifest)?;
    Ok(ManifestTestVector {
        row,
        manifest,
        binary,
    })
}

/// Encode [`EvidenceManifest`] to protobuf bytes (audit/replay wire shape).
pub fn encode_evidence_manifest_binary(manifest: &EvidenceManifest) -> Result<Vec<u8>, TarkaCoreError> {
    let mut buf = Vec::with_capacity(512);
    manifest
        .encode(&mut buf)
        .map_err(|e| TarkaCoreError::ManifestDecode(format!("protobuf encode: {e}")))?;
    Ok(buf)
}

/// Decode protobuf bytes into [`EvidenceManifest`].
pub fn decode_evidence_manifest_binary(bytes: &[u8]) -> Result<EvidenceManifest, TarkaCoreError> {
    EvidenceManifest::decode(bytes)
        .map_err(|e| TarkaCoreError::ManifestDecode(format!("protobuf decode: {e}")))
}

fn clickhouse_row_from_builder(builder: &ManifestTestVectorBuilder) -> EvidenceManifestRow {
    let mut signals = serde_json::Map::new();
    signals.insert("amount".into(), json!(builder.amount));
    if let Some(tx) = builder.transaction_id.as_ref() {
        signals.insert("transaction_id".into(), json!(tx));
    }
    if let Some(rule_id) = builder.rule_content_id.as_ref() {
        signals.insert("tarka.rule_content_id".into(), json!(rule_id));
    }

    let trace_json = json!(
        builder
            .trace_steps
            .iter()
            .map(trace_step_spec_to_json)
            .collect::<Vec<_>>()
    );

    EvidenceManifestRow {
        tenant_id: builder.tenant_id.clone(),
        manifest_id: builder.manifest_id.hyphenated().to_string(),
        engine_version: builder.engine_version.clone(),
        timestamp_ns: builder.timestamp_ns,
        final_decision: u8::from(builder.final_decision),
        total_execution_time_us: builder.total_execution_time_us,
        signals,
        trace_json,
        crypto_algorithm: builder.crypto_algorithm.clone(),
        crypto_signature_hex: builder.crypto_signature_hex.clone(),
        crypto_key_id: builder.crypto_key_id.clone(),
        raw_manifest_sha256: None,
    }
}

fn trace_step_spec_to_json(step: &TraceStepSpec) -> Value {
    json!({
        "rule_id": step.rule_id,
        "logic_operator": step.logic_operator,
        "operands": step.operands,
        "result": step.result,
        "state_snapshot": step.state_snapshot,
        "otel_trace_id": step.otel_trace_id,
    })
}

/// Ground-truth label row for mock ``normalized_labels`` lookups.
#[derive(Debug, Clone)]
pub struct GroundTruthLabelFixture {
    pub entity_id: String,
    pub ground_truth_class: String,
}

/// Ephemeral in-memory ClickHouse backed by wiremock HTTP (no live database).
pub struct MockClickHouseHarness {
    server: MockServer,
    database: String,
    table: String,
    labels_table: String,
    state: Arc<Mutex<MockClickHouseState>>,
}

#[derive(Debug, Default)]
struct MockClickHouseState {
    rows: Vec<EvidenceManifestRow>,
    labels: Vec<GroundTruthLabelFixture>,
}

impl MockClickHouseHarness {
    /// Start a wiremock listener and register a catch-all ClickHouse query handler.
    pub async fn spawn() -> Self {
        Self::spawn_with_options("tarka_audit", "evidence_manifests", "normalized_labels").await
    }

    pub async fn spawn_with_options(
        database: &str,
        table: &str,
        labels_table: &str,
    ) -> Self {
        let server = MockServer::start().await;
        let state = Arc::new(Mutex::new(MockClickHouseState::default()));
        let responder = ClickHouseQueryResponder {
            state: Arc::clone(&state),
            database: database.to_string(),
            table: table.to_string(),
            labels_table: labels_table.to_string(),
        };

        Mock::given(method("POST"))
            .respond_with(responder)
            .mount(&server)
            .await;

        Self {
            server,
            database: database.to_string(),
            table: table.to_string(),
            labels_table: labels_table.to_string(),
            state,
        }
    }

    pub fn base_url(&self) -> String {
        self.server.uri()
    }

  /// Insert a synthesized manifest row into the mock store.
    pub fn seed_vector(&self, vector: &ManifestTestVector) {
        let mut guard = self.state.lock().expect("mock clickhouse state lock");
        guard.rows.push(vector.row.clone());
    }

    pub fn seed_rows<I>(&self, rows: I)
    where
        I: IntoIterator<Item = EvidenceManifestRow>,
    {
        let mut guard = self.state.lock().expect("mock clickhouse state lock");
        guard.rows.extend(rows);
    }

    pub fn seed_ground_truth_labels<I>(&self, labels: I)
    where
        I: IntoIterator<Item = GroundTruthLabelFixture>,
    {
        let mut guard = self.state.lock().expect("mock clickhouse state lock");
        guard.labels.extend(labels);
    }

    /// Build a [`ClickhouseClient`] pointed at this harness (same database/table metadata).
    pub fn client(&self) -> ClickhouseClient {
        ClickhouseClient::try_new(
            self.base_url(),
            &self.database,
            &self.table,
            "default",
            "",
            Duration::from_secs(5),
            0,
        )
        .expect("mock clickhouse client must initialize")
    }

    pub fn labels_table(&self) -> &str {
        &self.labels_table
    }
}

struct ClickHouseQueryResponder {
    state: Arc<Mutex<MockClickHouseState>>,
    database: String,
    table: String,
    labels_table: String,
}

impl Respond for ClickHouseQueryResponder {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let query = std::str::from_utf8(&request.body).unwrap_or_default();
        let body = match route_clickhouse_query(
            query,
            &self.state,
            &self.database,
            &self.table,
            &self.labels_table,
        ) {
            Ok(body) => body,
            Err(err) => {
                return ResponseTemplate::new(500).set_body_string(format!("mock clickhouse: {err}"));
            }
        };
        ResponseTemplate::new(200).set_body_string(body)
    }
}

fn route_clickhouse_query(
    query: &str,
    state: &Arc<Mutex<MockClickHouseState>>,
    database: &str,
    table: &str,
    labels_table: &str,
) -> Result<String, CliError> {
    let normalized = query.replace(['\n', '\r'], " ");
    let guard = state.lock().map_err(|_| CliError::ClickHousePayload {
        reason: "mock clickhouse state poisoned".into(),
    })?;

    if normalized.contains(labels_table) {
        return Ok(render_normalized_labels(&normalized, &guard.labels));
    }

    if !normalized.contains(&format!("`{database}`.`{table}`")) {
        return Err(CliError::ClickHousePayload {
            reason: format!("unexpected mock query target: {query:.200}"),
        });
    }

    if normalized.contains("manifest_id = toUUID(") {
        let manifest_id = extract_manifest_id_from_query(&normalized).ok_or_else(|| {
            CliError::ClickHousePayload {
                reason: "mock single-manifest query missing manifest_id".into(),
            }
        })?;
        let row = guard
            .rows
            .iter()
            .find(|row| row.manifest_id.eq_ignore_ascii_case(&manifest_id))
            .ok_or_else(|| CliError::ManifestNotFound(Uuid::parse_str(&manifest_id).unwrap_or(Uuid::nil())))?;
        return Ok(format!("{}\n", serde_json::to_string(row).map_err(|e| {
            CliError::ClickHousePayload {
                reason: format!("mock row json encode: {e}"),
            }
        })?));
    }

    if normalized.contains("timestamp_ns >=") {
        let tenant = extract_quoted_literal_after(&normalized, "tenant_id = '")
            .ok_or_else(|| CliError::ClickHousePayload {
                reason: "mock window query missing tenant_id".into(),
            })?;
        let start_ts = extract_u64_after(&normalized, "timestamp_ns >= ")
            .ok_or_else(|| CliError::ClickHousePayload {
                reason: "mock window query missing start timestamp".into(),
            })?;
        let end_ts = extract_u64_after(&normalized, "timestamp_ns <= ")
            .ok_or_else(|| CliError::ClickHousePayload {
                reason: "mock window query missing end timestamp".into(),
            })?;
        let limit = extract_limit(&normalized).unwrap_or(usize::MAX);
        let cursor = parse_cursor_predicate(&normalized);

        let mut matched: Vec<&EvidenceManifestRow> = guard
            .rows
            .iter()
            .filter(|row| row.tenant_id == tenant)
            .filter(|row| row.timestamp_ns >= start_ts && row.timestamp_ns <= end_ts)
            .filter(|row| cursor_matches(row, cursor.as_ref()))
            .collect();

        matched.sort_by(|a, b| {
            a.timestamp_ns
                .cmp(&b.timestamp_ns)
                .then_with(|| a.manifest_id.cmp(&b.manifest_id))
        });
        matched.truncate(limit);

        let mut out = String::with_capacity(matched.len() * 256);
        for row in matched {
            out.push_str(&serde_json::to_string(row).map_err(|e| CliError::ClickHousePayload {
                reason: format!("mock row json encode: {e}"),
            })?);
            out.push('\n');
        }
        return Ok(out);
    }

    Err(CliError::ClickHousePayload {
        reason: format!("unsupported mock clickhouse query: {query:.200}"),
    })
}

fn render_normalized_labels(query: &str, labels: &[GroundTruthLabelFixture]) -> String {
    let requested = extract_in_list_entity_ids(query);
    let mut out = String::with_capacity(labels.len() * 64);
    for label in labels {
        if !requested.is_empty() && !requested.contains(&label.entity_id) {
            continue;
        }
        let row = NormalizedLabelRow {
            entity_id: label.entity_id.clone(),
            ground_truth_class: label.ground_truth_class.clone(),
        };
        if let Ok(line) = serde_json::to_string(&row) {
            out.push_str(&line);
            out.push('\n');
        }
    }
    out
}

fn extract_in_list_entity_ids(query: &str) -> HashSet<String> {
    let Some(start) = query.find("entity_id IN (") else {
        return HashSet::new();
    };
    let rest = &query[start + "entity_id IN (".len()..];
    let Some(end) = rest.find(')') else {
        return HashSet::new();
    };
    rest[..end]
        .split(',')
        .filter_map(|token| {
            let trimmed = token.trim().trim_matches('\'');
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        })
        .collect()
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WindowCursor {
    timestamp_ns: u64,
    manifest_id: String,
}

fn parse_cursor_predicate(query: &str) -> Option<WindowCursor> {
    if !query.contains("timestamp_ns >") {
        return None;
    }
    let ts = extract_u64_after(query, "timestamp_ns > ")?;
    let manifest_id = extract_to_uuid_literal(query)?;
    Some(WindowCursor {
        timestamp_ns: ts,
        manifest_id,
    })
}

fn cursor_matches(row: &EvidenceManifestRow, cursor: Option<&WindowCursor>) -> bool {
    let Some(cursor) = cursor else {
        return true;
    };
    row.timestamp_ns > cursor.timestamp_ns
        || (row.timestamp_ns == cursor.timestamp_ns && row.manifest_id > cursor.manifest_id)
}

fn extract_manifest_id_from_query(query: &str) -> Option<String> {
    extract_quoted_literal_after(query, "manifest_id = toUUID('")
}

fn extract_to_uuid_literal(query: &str) -> Option<String> {
    let idx = query.find("manifest_id > toUUID(")?;
    let rest = &query[idx + "manifest_id > toUUID(".len()..];
    let end = rest.find(')')?;
    Some(rest[..end].trim().trim_matches('\'').to_string())
}

fn extract_quoted_literal_after(query: &str, needle: &str) -> Option<String> {
    let idx = query.find(needle)?;
    let rest = &query[idx + needle.len()..];
    let end = rest.find('\'')?;
    Some(rest[..end].to_string())
}

fn extract_u64_after(query: &str, needle: &str) -> Option<u64> {
    let idx = query.find(needle)?;
    let rest = query[idx + needle.len()..].trim();
    let token: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    token.parse().ok()
}

fn extract_limit(query: &str) -> Option<usize> {
    let idx = query.find("LIMIT ")?;
    let rest = query[idx + "LIMIT ".len()..].trim();
    let token: String = rest
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .collect();
    token.parse().ok()
}

/// Batch-generate ``count`` vectors with monotonic timestamps (streaming replay tests).
pub fn synthesize_manifest_batch(
    count: usize,
    tenant_id: &str,
    base_timestamp_ns: u64,
) -> Result<Vec<ManifestTestVector>, TarkaCoreError> {
    let mut out = Vec::with_capacity(count);
    for index in 0..count {
        let vector = ManifestTestVectorBuilder::new()
            .manifest_id(Uuid::new_v4())
            .tenant_id(tenant_id)
            .timestamp_ns(base_timestamp_ns + index as u64)
            .transaction_id(format!("tx-batch-{index}"))
            .build()?;
        out.push(vector);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clickhouse::MANIFEST_BATCH_STREAM_CHUNK;
    use crate::replay::fetch_manifest_batch_by_window;

    #[test]
    fn manifest_vector_binary_roundtrip() {
        let vector = ManifestTestVectorBuilder::new()
            .amount(9_999.0)
            .final_decision(true)
            .build()
            .expect("build vector");

        assert!(!vector.binary.is_empty());
        let decoded = decode_evidence_manifest_binary(&vector.binary).expect("decode");
        assert_eq!(decoded, vector.manifest);
        assert_eq!(
            decoded
                .metadata
                .as_ref()
                .map(|m| m.final_decision)
                .unwrap_or(false),
            true
        );
    }

    #[tokio::test]
    async fn mock_clickhouse_serves_window_and_single_manifest_queries() {
        let harness = MockClickHouseHarness::spawn().await;
        let vector = ManifestTestVectorBuilder::new()
            .tenant_id("parity-demo")
            .timestamp_ns(1_700_000_000_000_000_000)
            .build()
            .expect("vector");
        harness.seed_vector(&vector);

        let client = harness.client();
        let fetched = fetch_manifest_batch_by_window(
            &client,
            1_700_000_000_000_000_000_i64,
            1_700_000_000_000_000_999_i64,
            "parity-demo",
        )
        .await
        .expect("window fetch");

        assert_eq!(fetched.len(), 1);
        assert_eq!(
            fetched[0]
                .header
                .as_ref()
                .and_then(|h| Uuid::from_slice(h.manifest_id.as_slice()).ok())
                .map(|u| u.hyphenated().to_string()),
            Some(vector.row.manifest_id.clone())
        );

        let batch = synthesize_manifest_batch(3, "parity-demo", 1_700_000_000_000_001_000)
            .expect("batch");
        harness.seed_rows(batch.iter().map(|v| v.row.clone()));

        let page = client
            .fetch_manifest_rows_window_page(
                1_700_000_000_000_001_000,
                1_700_000_000_000_002_000,
                "parity-demo",
                None,
                MANIFEST_BATCH_STREAM_CHUNK,
            )
            .await
            .expect("page");
        assert_eq!(page.len(), 3);
    }

    #[tokio::test]
    async fn mock_clickhouse_serves_ground_truth_label_lookups() {
        let harness = MockClickHouseHarness::spawn().await;
        harness.seed_ground_truth_labels([GroundTruthLabelFixture {
            entity_id: "tx-1".into(),
            ground_truth_class: "FRAUD".into(),
        }]);

        let client = harness.client();
        let labels = client
            .fetch_active_ground_truth_labels(
                "test-tenant",
                harness.labels_table(),
                &[String::from("tx-1")],
            )
            .await
            .expect("labels");

        assert_eq!(labels.get("tx-1"), Some(&true));
    }
}
