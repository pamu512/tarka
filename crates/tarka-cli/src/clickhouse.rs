//! ClickHouse HTTP interface: bounded timeouts and retries with jittered backoff.

use std::time::Duration;

use std::collections::{HashMap, HashSet};

use reqwest::header::CONTENT_TYPE;
use serde::Deserialize;
use serde_json::Value;
use tokio::time::sleep;
use url::Url;
use uuid::Uuid;

use crate::error::CliError;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

/// Memory-safe upper bound for one windowed manifest pull (see [`fetch_manifest_rows_by_window`]).
pub const MAX_MANIFEST_BATCH_WINDOW_PULL: usize = 50_000;

/// Streaming page size for tenant/window manifest pulls (keyset pagination).
pub const MANIFEST_BATCH_STREAM_CHUNK: usize = 2_048;

/// Chunk size for `IN (...)` ground-truth label lookups (keeps HTTP payloads bounded).
pub const GROUND_TRUTH_LABEL_LOOKUP_CHUNK: usize = 1_000;

/// Keyset cursor for stable ``ORDER BY timestamp_ns, manifest_id`` pagination.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManifestWindowBookmark {
    pub timestamp_ns: u64,
    pub manifest_id: String,
}

fn validate_sql_identifier(value: &str, context: &'static str) -> Result<(), CliError> {
    if !value.is_empty() && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Ok(());
    }
    Err(CliError::InvalidIdentifier {
        context,
        value: value.to_string(),
    })
}

#[derive(Debug, Clone, Deserialize, serde::Serialize)]
pub struct EvidenceManifestRow {
    #[serde(default)]
    pub tenant_id: String,
    pub manifest_id: String,
    pub engine_version: String,
    pub timestamp_ns: u64,
    pub final_decision: u8,
    pub total_execution_time_us: u64,
    /// ClickHouse Map becomes JSON object; values may be strings or nested JSON (depending on driver path).
    pub signals: serde_json::Map<String, Value>,
    pub trace_json: Value,
    pub crypto_algorithm: String,
    pub crypto_signature_hex: String,
    pub crypto_key_id: String,
    #[serde(default)]
    pub raw_manifest_sha256: Option<String>,
    /// Hex-encoded wire `EvidenceManifest` protobuf when ClickHouse stores `raw_manifest`.
    #[serde(default)]
    pub raw_manifest_hex: Option<String>,
    /// Hex-encoded 32-byte digest (`hex(raw_manifest_sha256)` in queries).
    #[serde(default)]
    pub raw_manifest_sha256_hex: Option<String>,
}

/// Active ground-truth row from the ClickHouse ``normalized_labels`` mirror.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, serde::Serialize)]
pub struct NormalizedLabelRow {
    pub entity_id: String,
    pub ground_truth_class: String,
}

/// Configured ClickHouse HTTP client for evidence manifest queries.
#[derive(Debug, Clone)]
pub struct ClickhouseClient {
    pub http: reqwest::Client,
    pub base_url: String,
    pub database: String,
    pub table: String,
    pub user: String,
    pub password: String,
    pub timeout: Duration,
    pub max_retries: u32,
}

impl ClickhouseClient {
    pub fn try_new(
        base_url: impl Into<String>,
        database: impl Into<String>,
        table: impl Into<String>,
        user: impl Into<String>,
        password: impl Into<String>,
        timeout: Duration,
        max_retries: u32,
    ) -> Result<Self, CliError> {
        let database = database.into();
        let table = table.into();
        validate_sql_identifier(&database, "database")?;
        validate_sql_identifier(&table, "table")?;
        Ok(Self {
            http: build_http_client()?,
            base_url: base_url.into(),
            database,
            table,
            user: user.into(),
            password: password.into(),
            timeout,
            max_retries,
        })
    }

    pub async fn post_query(
        &self,
        tenant_id: Option<&str>,
        query: &str,
    ) -> Result<String, CliError> {
        http_post_query_with_retry(
            &self.http,
            &self.base_url,
            &self.database,
            &self.user,
            &self.password,
            tenant_id,
            query,
            self.timeout,
            self.max_retries,
        )
        .await
    }

    /// Fetch up to [`MAX_MANIFEST_BATCH_WINDOW_PULL`] manifest rows for a tenant/time window.
    ///
    /// Uses keyset pagination internally ([`MANIFEST_BATCH_STREAM_CHUNK`]) so ClickHouse responses
    /// are processed in bounded chunks. Returns `ClickHousePayload` when the window exceeds the cap.
    pub async fn fetch_manifest_rows_by_window(
        &self,
        start_ts: i64,
        end_ts: i64,
        tenant_id: &str,
    ) -> Result<Vec<EvidenceManifestRow>, CliError> {
        let mut all = Vec::with_capacity(MANIFEST_BATCH_STREAM_CHUNK.min(MAX_MANIFEST_BATCH_WINDOW_PULL));
        let mut cursor: Option<ManifestWindowBookmark> = None;

        loop {
            let page = self
                .fetch_manifest_rows_window_page(
                    start_ts,
                    end_ts,
                    tenant_id,
                    cursor.as_ref(),
                    MANIFEST_BATCH_STREAM_CHUNK,
                )
                .await?;

            if page.is_empty() {
                break;
            }

            if all.len() + page.len() > MAX_MANIFEST_BATCH_WINDOW_PULL {
                return Err(CliError::ClickHousePayload {
                    reason: format!(
                        "manifest batch window returned more than {} rows (memory-safe cap)",
                        MAX_MANIFEST_BATCH_WINDOW_PULL,
                    ),
                });
            }

            cursor = page.last().map(ManifestWindowBookmark::from_row);
            let page_len = page.len();
            all.extend(page);

            if page_len < MANIFEST_BATCH_STREAM_CHUNK {
                break;
            }
        }

        Ok(all)
    }

    /// Fetch one keyset page of manifest rows for streaming batch replay.
    ///
    /// Pass ``cursor`` from the previous page's last row (via [`ManifestWindowBookmark::from_row`])
    /// until an empty page is returned.
    pub async fn fetch_manifest_rows_window_page(
        &self,
        start_ts: i64,
        end_ts: i64,
        tenant_id: &str,
        cursor: Option<&ManifestWindowBookmark>,
        chunk_limit: usize,
    ) -> Result<Vec<EvidenceManifestRow>, CliError> {
        validate_manifest_window_bounds(start_ts, end_ts, tenant_id)?;

        if chunk_limit == 0 {
            return Ok(Vec::new());
        }

        let start_u = start_ts as u64;
        let end_u = end_ts as u64;
        let tenant_esc = escape_sql_string(tenant_id.trim());
        let cursor_sql = cursor
            .map(format_manifest_window_bookmark_predicate)
            .unwrap_or_default();

        let q = format!(
            "SELECT tenant_id, manifest_id, engine_version, timestamp_ns, final_decision, total_execution_time_us, \
             signals, trace_json, crypto_algorithm, crypto_signature_hex, crypto_key_id, raw_manifest_sha256 \
             FROM `{database}`.`{table}` \
             WHERE tenant_id = '{tenant_esc}' \
               AND timestamp_ns >= {start_u} \
               AND timestamp_ns <= {end_u} \
               {cursor_sql} \
             ORDER BY timestamp_ns ASC, manifest_id ASC \
             LIMIT {chunk_limit} \
             FORMAT JSONEachRow",
            database = self.database,
            table = self.table,
            tenant_esc = tenant_esc,
            start_u = start_u,
            end_u = end_u,
            cursor_sql = cursor_sql,
            chunk_limit = chunk_limit,
        );

        let body = self.post_query(Some(tenant_id.trim()), &q).await?;
        parse_manifest_rows_chunk(&body, chunk_limit)
    }

    /// Stream manifest rows in fixed-size chunks without holding the full window in memory.
    ///
    /// Stops when the page is empty or [`MAX_MANIFEST_BATCH_WINDOW_PULL`] rows have been delivered.
    /// Returns the total row count delivered to the callback.
    pub async fn stream_manifest_rows_by_window<F>(
        &self,
        start_ts: i64,
        end_ts: i64,
        tenant_id: &str,
        chunk_limit: usize,
        mut on_chunk: F,
    ) -> Result<usize, CliError>
    where
        F: FnMut(Vec<EvidenceManifestRow>) -> Result<(), CliError>,
    {
        let limit = if chunk_limit == 0 {
            MANIFEST_BATCH_STREAM_CHUNK
        } else {
            chunk_limit
        };

        let mut cursor: Option<ManifestWindowBookmark> = None;
        let mut delivered = 0usize;

        loop {
            let page = self
                .fetch_manifest_rows_window_page(
                    start_ts,
                    end_ts,
                    tenant_id,
                    cursor.as_ref(),
                    limit,
                )
                .await?;

            if page.is_empty() {
                break;
            }

            let page_len = page.len();
            if delivered + page_len > MAX_MANIFEST_BATCH_WINDOW_PULL {
                return Err(CliError::ClickHousePayload {
                    reason: format!(
                        "manifest batch window exceeded memory-safe cap {} during streaming",
                        MAX_MANIFEST_BATCH_WINDOW_PULL,
                    ),
                });
            }

            cursor = page.last().map(ManifestWindowBookmark::from_row);
            delivered += page_len;
            on_chunk(page)?;

            if page_len < limit {
                break;
            }
        }

        Ok(delivered)
    }

    /// Cross-reference processed transaction/entity ids against active ground-truth labels.
    ///
    /// Returns a map keyed by ``entity_id`` where ``true`` means ``FRAUD`` and ``false`` means
    /// ``LEGITIMATE``. When multiple rows exist per entity, the label with the latest
    /// ``created_at`` wins (``argMax``).
    pub async fn fetch_active_ground_truth_labels(
        &self,
        tenant_id: &str,
        labels_table: &str,
        entity_ids: &[String],
    ) -> Result<HashMap<String, bool>, CliError> {
        if entity_ids.is_empty() {
            return Ok(HashMap::new());
        }
        if tenant_id.trim().is_empty() {
            return Err(CliError::ClickHousePayload {
                reason: "tenant_id must be non-empty for normalized_labels lookup".into(),
            });
        }
        validate_sql_identifier(labels_table, "normalized_labels table")?;

        let tenant_esc = escape_sql_string(tenant_id.trim());
        let mut unique: Vec<String> = entity_ids
            .iter()
            .map(|id| id.trim().to_string())
            .filter(|id| !id.is_empty())
            .collect();
        unique.sort_unstable();
        unique.dedup();

        let mut out = HashMap::with_capacity(unique.len());
        for chunk in unique.chunks(GROUND_TRUTH_LABEL_LOOKUP_CHUNK) {
            let in_list = chunk
                .iter()
                .map(|id| format!("'{}'", escape_sql_string(id)))
                .collect::<Vec<_>>()
                .join(", ");
            let q = format!(
                "SELECT entity_id, ground_truth_class \
                 FROM ( \
                   SELECT \
                     entity_id, \
                     argMax(ground_truth_class, created_at) AS ground_truth_class \
                   FROM `{database}`.`{labels_table}` \
                   WHERE tenant_id = '{tenant_esc}' \
                     AND label_active = 1 \
                     AND entity_id IN ({in_list}) \
                   GROUP BY entity_id \
                 ) \
                 FORMAT JSONEachRow",
                database = self.database,
                labels_table = labels_table,
                tenant_esc = tenant_esc,
                in_list = in_list,
            );

            let body = self.post_query(Some(tenant_id.trim()), &q).await?;
            for line in body.lines().filter(|l| !l.trim().is_empty()) {
                let row: NormalizedLabelRow = serde_json::from_str(line).map_err(|e| {
                    CliError::ClickHousePayload {
                        reason: format!("normalized_labels JSONEachRow parse: {e}; line={line:.200}"),
                    }
                })?;
                let Some(is_fraud) = parse_ground_truth_class(&row.ground_truth_class) else {
                    continue;
                };
                out.insert(row.entity_id, is_fraud);
            }
        }

        Ok(out)
    }
}

pub async fn fetch_manifest_row(
    http: &reqwest::Client,
    base_url: &str,
    database: &str,
    table: &str,
    user: &str,
    password: &str,
    manifest_id: Uuid,
    timeout: Duration,
    max_retries: u32,
    row_policy_tenant_id: Option<&str>,
) -> Result<EvidenceManifestRow, CliError> {
    validate_sql_identifier(database, "database")?;
    validate_sql_identifier(table, "table")?;

    let id_str = manifest_id.hyphenated().to_string();
    let q = format!(
        "SELECT tenant_id, manifest_id, engine_version, timestamp_ns, final_decision, total_execution_time_us, \
         signals, trace_json, crypto_algorithm, crypto_signature_hex, crypto_key_id, raw_manifest_sha256 \
         FROM `{database}`.`{table}` \
         WHERE manifest_id = toUUID('{id_str}') \
         LIMIT 1 \
         FORMAT JSONEachRow"
    );

    let body = http_post_query_with_retry(
        http,
        base_url,
        database,
        user,
        password,
        row_policy_tenant_id,
        &q,
        timeout,
        max_retries,
    )
    .await?;

    let line = body.lines().find(|l| !l.trim().is_empty());
    let Some(line) = line else {
        return Err(CliError::ManifestNotFound(manifest_id));
    };

    let row: EvidenceManifestRow = serde_json::from_str(line).map_err(|e| CliError::ClickHousePayload {
        reason: format!("JSONEachRow parse: {e}; line={line:.200}"),
    })?;

    Ok(row)
}

impl ManifestWindowBookmark {
    pub fn from_row(row: &EvidenceManifestRow) -> Self {
        Self {
            timestamp_ns: row.timestamp_ns,
            manifest_id: row.manifest_id.clone(),
        }
    }
}

fn validate_manifest_window_bounds(
    start_ts: i64,
    end_ts: i64,
    tenant_id: &str,
) -> Result<(), CliError> {
    if tenant_id.trim().is_empty() {
        return Err(CliError::ClickHousePayload {
            reason: "tenant_id must be non-empty".into(),
        });
    }
    if start_ts > end_ts {
        return Err(CliError::ClickHousePayload {
            reason: format!("invalid replay window: start_ts ({start_ts}) > end_ts ({end_ts})"),
        });
    }
    if start_ts < 0 {
        return Err(CliError::ClickHousePayload {
            reason: format!("replay window start_ts must be non-negative, got {start_ts}"),
        });
    }
    Ok(())
}

fn format_manifest_window_bookmark_predicate(cursor: &ManifestWindowBookmark) -> String {
    let id_esc = escape_sql_string(cursor.manifest_id.trim());
    format!(
        "AND (timestamp_ns > {ts} OR (timestamp_ns = {ts} AND manifest_id > toUUID('{id_esc}')))",
        ts = cursor.timestamp_ns,
        id_esc = id_esc,
    )
}

/// Parse a JSONEachRow HTTP body into a pre-capacity vector (at most ``chunk_limit`` rows).
fn parse_manifest_rows_chunk(body: &str, chunk_limit: usize) -> Result<Vec<EvidenceManifestRow>, CliError> {
    let mut rows = Vec::with_capacity(chunk_limit);
    for line in body.lines() {
        if line.trim().is_empty() {
            continue;
        }
        if rows.len() >= chunk_limit {
            break;
        }
        let row: EvidenceManifestRow = serde_json::from_str(line).map_err(|e| {
            CliError::ClickHousePayload {
                reason: format!("JSONEachRow parse: {e}; line={line:.200}"),
            }
        })?;
        rows.push(row);
    }
    Ok(rows)
}

fn escape_sql_string(s: &str) -> String {
    s.replace('\\', "\\\\").replace('\'', "\\'")
}

/// Parse consortium ground-truth enum into fraud-positive semantics for classifier metrics.
pub fn parse_ground_truth_class(raw: &str) -> Option<bool> {
    match raw.trim().to_ascii_uppercase().as_str() {
        "FRAUD" => Some(true),
        "LEGITIMATE" | "LEGIT" => Some(false),
        _ => None,
    }
}

/// Collect unique transaction/entity ids from manifest signal maps for label cross-reference.
pub fn collect_transaction_ids_from_signal_maps(
    signal_maps: impl IntoIterator<Item = serde_json::Map<String, Value>>,
) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for signals in signal_maps {
        if let Some(id) = transaction_id_from_signal_map(&signals) {
            if seen.insert(id.clone()) {
                out.push(id);
            }
        }
    }
    out.sort_unstable();
    out
}

/// Resolve the transaction anchor used by ``normalized_labels.entity_id``.
pub fn transaction_id_from_signal_map(signals: &serde_json::Map<String, Value>) -> Option<String> {
    for key in [
        "transaction_id",
        "entity_id",
        "tarka.transaction_id",
        "user_id",
        "subject_id",
    ] {
        if let Some(raw) = signals.get(key) {
            if let Some(token) = signal_scalar_to_string(raw) {
                let trimmed = token.trim();
                if !trimmed.is_empty() {
                    return Some(trimmed.to_string());
                }
            }
        }
    }
    None
}

fn signal_scalar_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

async fn http_post_query_with_retry(
    http: &reqwest::Client,
    base_url: &str,
    database: &str,
    user: &str,
    password: &str,
    row_policy_tenant_id: Option<&str>,
    query: &str,
    timeout: Duration,
    max_retries: u32,
) -> Result<String, CliError> {
    let base = base_url.trim_end_matches('/');
    let mut url = Url::parse(&format!("{base}/")).map_err(|e| CliError::ClickHousePayload {
        reason: format!("invalid ClickHouse URL: {e}"),
    })?;
    {
        let mut pairs = url.query_pairs_mut();
        pairs.append_pair("database", database);
        if let Some(tid) = row_policy_tenant_id.filter(|s| !s.is_empty()) {
            pairs.append_pair("tarka_tenant_id", tid);
        }
    }
    let url = url.to_string();

    let mut last_err: Option<reqwest::Error> = None;
    for attempt in 0..=max_retries {
        if attempt > 0 {
            let base_ms = 200u64 * 2u64.pow(attempt - 1);
            let jitter = (attempt as u64 * 17) % 100;
            sleep(Duration::from_millis(base_ms + jitter)).await;
        }

        let send_fut = http
            .post(&url)
            .basic_auth(user, Some(password))
            .header(CONTENT_TYPE, "text/plain; charset=utf-8")
            .body(query.to_string())
            .send();

        let res = match tokio::time::timeout(timeout, send_fut).await {
            Ok(Ok(r)) => r,
            Ok(Err(e)) => {
                last_err = Some(e);
                continue;
            }
            Err(_elapsed) => {
                if attempt == max_retries {
                    return Err(CliError::ClickHouseTimeout(timeout));
                }
                continue;
            }
        };

        let status = res.status();
        if status.is_success() {
            return res.text().await.map_err(|e| CliError::ClickHouseTransport { source: e });
        }

        let snippet = res.text().await.unwrap_or_default();
        if status.is_server_error() || status == reqwest::StatusCode::TOO_MANY_REQUESTS {
            if attempt == max_retries {
                return Err(CliError::ClickHouseHttp {
                    status,
                    snippet: truncate(&snippet, 512),
                });
            }
            continue;
        }

        return Err(CliError::ClickHouseHttp {
            status,
            snippet: truncate(&snippet, 512),
        });
    }

    Err(CliError::ClickHouseTransport {
        source: last_err.expect("retry loop without error"),
    })
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max])
    }
}

pub fn build_http_client() -> Result<reqwest::Client, CliError> {
    reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .build()
        .map_err(|e| CliError::ClickHouseTransport { source: e })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parse_ground_truth_class_maps_fraud_and_legitimate() {
        assert_eq!(parse_ground_truth_class("FRAUD"), Some(true));
        assert_eq!(parse_ground_truth_class("legitimate"), Some(false));
        assert_eq!(parse_ground_truth_class("unknown"), None);
    }

    #[test]
    fn transaction_id_prefers_transaction_id_key() {
        let mut signals = serde_json::Map::new();
        signals.insert("entity_id".into(), json!("ent-1"));
        signals.insert("transaction_id".into(), json!("tx-9"));
        assert_eq!(
            transaction_id_from_signal_map(&signals).as_deref(),
            Some("tx-9")
        );
    }

    #[test]
    fn collect_transaction_ids_deduplicates_signal_maps() {
        let mut a = serde_json::Map::new();
        a.insert("transaction_id".into(), json!("tx-1"));
        let mut b = serde_json::Map::new();
        b.insert("transaction_id".into(), json!("tx-1"));
        let mut c = serde_json::Map::new();
        c.insert("entity_id".into(), json!("tx-2"));
        let ids = collect_transaction_ids_from_signal_maps([a, b, c]);
        assert_eq!(ids, vec!["tx-1".to_string(), "tx-2".to_string()]);
    }

    #[test]
    fn parse_manifest_rows_chunk_preallocates_and_respects_limit() {
        let body = (0..4)
            .map(|i| {
                format!(
                    r#"{{"manifest_id":"550e8400-e29b-41d4-a716-44665544000{i}","engine_version":"0.1.0","timestamp_ns":{i},"final_decision":0,"total_execution_time_us":1,"signals":{{}},"trace_json":[],"crypto_algorithm":"none","crypto_signature_hex":"","crypto_key_id":""}}"#
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let rows = parse_manifest_rows_chunk(&body, 2).expect("parse");
        assert_eq!(rows.len(), 2);
        assert!(rows.capacity() >= 2);
    }

    #[test]
    fn cursor_predicate_uses_timestamp_and_manifest_id() {
        let cursor = ManifestWindowBookmark {
            timestamp_ns: 42,
            manifest_id: "550e8400-e29b-41d4-a716-446655440000".into(),
        };
        let sql = format_manifest_window_bookmark_predicate(&cursor);
        assert!(sql.contains("timestamp_ns > 42"));
        assert!(sql.contains("manifest_id > toUUID"));
    }
}
