//! ClickHouse HTTP interface: bounded timeouts and retries with jittered backoff.

use std::time::Duration;

use reqwest::header::CONTENT_TYPE;
use serde::Deserialize;
use serde_json::Value;
use tokio::time::sleep;
use url::Url;
use uuid::Uuid;

use crate::error::CliError;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

fn validate_sql_identifier(value: &str, context: &'static str) -> Result<(), CliError> {
    if !value.is_empty() && value.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Ok(());
    }
    Err(CliError::InvalidIdentifier {
        context,
        value: value.to_string(),
    })
}

#[derive(Debug, Deserialize)]
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
