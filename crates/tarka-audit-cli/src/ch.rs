//! ClickHouse HTTP client (timeouts, exponential backoff + jitter) — mirrors `tarka-cli` patterns.

use std::time::Duration;

use reqwest::header::CONTENT_TYPE;
use serde::Deserialize;
use tokio::time::sleep;
use url::Url;

use tarka_cli::clickhouse::EvidenceManifestRow;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug)]
pub struct ClickHouseParams {
    pub base_url: String,
    pub database: String,
    pub evidence_table: String,
    pub otel_spans_table: String,
    pub user: String,
    pub password: String,
    pub row_policy_tenant_id: Option<String>,
    pub timeout: Duration,
    pub max_retries: u32,
}

#[derive(Debug, Deserialize)]
pub struct OtelTraceStats {
    #[serde(rename = "span_count")]
    pub span_count: u64,
    #[serde(rename = "min_ts", default)]
    pub min_timestamp: Option<String>,
    #[serde(rename = "max_ts", default)]
    pub max_timestamp: Option<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum ClickHouseError {
    #[error("invalid SQL identifier for {context}: {value}")]
    InvalidIdentifier {
        context: &'static str,
        value: String,
    },
    #[error("ClickHouse HTTP {status}: {snippet}")]
    Http {
        status: reqwest::StatusCode,
        snippet: String,
    },
    #[error("ClickHouse request timed out after {0:?}")]
    Timeout(Duration),
    #[error("ClickHouse transport error: {source}")]
    Transport {
        #[source]
        source: reqwest::Error,
    },
    #[error("ClickHouse payload error: {reason}")]
    Payload { reason: String },
    #[error("no evidence_manifest row linked this trace id (check trace_json.otel_trace_id is populated for newer ingestor builds)")]
    ManifestNotFound,
    #[error("ambiguous: multiple manifests match this trace id; re-run with --latest or narrow data")]
    AmbiguousManifest,
}

pub fn build_http_client() -> Result<reqwest::Client, ClickHouseError> {
    reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .build()
        .map_err(|source| ClickHouseError::Transport { source })
}

fn validate_sql_identifier(value: &str, context: &'static str) -> Result<(), ClickHouseError> {
    if !value.is_empty() && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Ok(());
    }
    Err(ClickHouseError::InvalidIdentifier {
        context,
        value: value.to_string(),
    })
}

pub async fn otel_trace_present(
    http: &reqwest::Client,
    p: &ClickHouseParams,
    tid: &str,
) -> Result<OtelTraceStats, ClickHouseError> {
    validate_sql_identifier(&p.database, "database")?;
    validate_sql_identifier(&p.otel_spans_table, "otel_spans_table")?;

    let q = format!(
        "SELECT \
           count() AS span_count, \
           min(Timestamp) AS min_ts, \
           max(Timestamp) AS max_ts \
         FROM `{db}`.`{otel}` \
         WHERE TraceId = '{tid}' \
         FORMAT JSONEachRow",
        db = p.database,
        otel = p.otel_spans_table,
        tid = escape_sql_string(tid),
    );

    let body = http_post_query_with_retry(http, p, &q).await?;
    let line = body.lines().find(|l| !l.trim().is_empty());
    let Some(line) = line else {
        return Err(ClickHouseError::Payload {
            reason: "empty OTel stats response".into(),
        });
    };

    serde_json::from_str::<OtelTraceStats>(line).map_err(|e| ClickHouseError::Payload {
        reason: format!("JSONEachRow otel stats: {e}; line={line:.300}"),
    })
}

pub async fn fetch_manifest_for_trace(
    http: &reqwest::Client,
    p: &ClickHouseParams,
    tid: &str,
    latest: bool,
) -> Result<EvidenceManifestRow, ClickHouseError> {
    validate_sql_identifier(&p.database, "database")?;
    validate_sql_identifier(&p.evidence_table, "evidence_table")?;

    let limit = if latest { 1 } else { 2 };
    let tid_esc = escape_sql_string(tid);
    let q = format!(
        "SELECT \
           tenant_id, manifest_id, engine_version, timestamp_ns, final_decision, total_execution_time_us, \
           signals, trace_json, crypto_algorithm, crypto_signature_hex, crypto_key_id, raw_manifest_sha256 \
         FROM `{db}`.`{tbl}` \
         WHERE arrayExists( \
           obj -> lower(replaceAll(JSONExtractString(obj, 'otel_trace_id'), '-', '')) = '{tid}', \
           JSONExtractArrayRaw(toJSONString(trace_json)) \
         ) \
         ORDER BY timestamp_ns DESC \
         LIMIT {limit} \
         FORMAT JSONEachRow",
        db = p.database,
        tbl = p.evidence_table,
        tid = tid_esc,
        limit = limit,
    );

    let body = http_post_query_with_retry(http, p, &q).await?;
    let lines: Vec<&str> = body.lines().filter(|l| !l.trim().is_empty()).collect();
    if lines.is_empty() {
        return Err(ClickHouseError::ManifestNotFound);
    }
    if !latest && lines.len() > 1 {
        return Err(ClickHouseError::AmbiguousManifest);
    }

    let row: EvidenceManifestRow = serde_json::from_str(lines[0]).map_err(|e| {
        ClickHouseError::Payload {
            reason: format!("JSONEachRow manifest parse: {e}; line={:.300}", lines[0]),
        }
    })?;

    Ok(row)
}

fn escape_sql_string(s: &str) -> String {
    s.replace('\\', "\\\\").replace('\'', "\\'")
}

async fn http_post_query_with_retry(
    http: &reqwest::Client,
    p: &ClickHouseParams,
    query: &str,
) -> Result<String, ClickHouseError> {
    let base = p.base_url.trim_end_matches('/');
    let mut url = Url::parse(&format!("{base}/")).map_err(|e| ClickHouseError::Payload {
        reason: format!("invalid ClickHouse URL: {e}"),
    })?;
    {
        let mut pairs = url.query_pairs_mut();
        pairs.append_pair("database", &p.database);
        if let Some(tid) = p.row_policy_tenant_id.as_ref().filter(|s| !s.is_empty()) {
            pairs.append_pair("tarka_tenant_id", tid);
        }
    }
    let url = url.to_string();

    let mut last_err: Option<reqwest::Error> = None;
    for attempt in 0..=p.max_retries {
        if attempt > 0 {
            let base_ms = 200u64 * 2u64.pow(attempt - 1);
            let jitter = (attempt as u64 * 17) % 100;
            sleep(Duration::from_millis(base_ms + jitter)).await;
        }

        let send_fut = http
            .post(&url)
            .basic_auth(&p.user, Some(&p.password))
            .header(CONTENT_TYPE, "text/plain; charset=utf-8")
            .body(query.to_string())
            .send();

        let res = match tokio::time::timeout(p.timeout, send_fut).await {
            Ok(Ok(r)) => r,
            Ok(Err(e)) => {
                last_err = Some(e);
                continue;
            }
            Err(_elapsed) => {
                if attempt == p.max_retries {
                    return Err(ClickHouseError::Timeout(p.timeout));
                }
                continue;
            }
        };

        let status = res.status();
        if status.is_success() {
            return res
                .text()
                .await
                .map_err(|source| ClickHouseError::Transport { source });
        }

        let snippet = res.text().await.unwrap_or_default();
        if status.is_server_error() || status == reqwest::StatusCode::TOO_MANY_REQUESTS {
            if attempt == p.max_retries {
                return Err(ClickHouseError::Http {
                    status,
                    snippet: truncate(&snippet, 512),
                });
            }
            continue;
        }

        return Err(ClickHouseError::Http {
            status,
            snippet: truncate(&snippet, 512),
        });
    }

    Err(ClickHouseError::Transport {
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
