//! Immutable rule registry HTTP client (contract documented for management-plane integration).

use std::time::Duration;

use reqwest::header::ACCEPT;
use serde::Deserialize;
use tokio::time::sleep;

use crate::error::CliError;

#[derive(Debug, Deserialize)]
pub struct RegistryRuleResponse {
    pub rule_body: String,
    #[serde(default)]
    pub content_hash: Option<String>,
    #[serde(default)]
    pub rule_name: Option<String>,
}

pub async fn fetch_rule_by_content_hash(
    http: &reqwest::Client,
    registry_base: &str,
    content_hash_hex: &str,
    timeout: Duration,
    max_retries: u32,
) -> Result<RegistryRuleResponse, CliError> {
    let base = registry_base.trim_end_matches('/');
    let url = format!("{base}/v1/registry/rules/by-content-hash/{content_hash_hex}");

    for attempt in 0..=max_retries {
        if attempt > 0 {
            let base_ms = 200u64 * 2u64.pow(attempt - 1);
            let jitter = (attempt as u64 * 23) % 120;
            sleep(Duration::from_millis(base_ms + jitter)).await;
        }

        let send_fut = http
            .get(&url)
            .header(ACCEPT, "application/json")
            .timeout(timeout)
            .send();

        let res = match send_fut.await {
            Ok(r) => r,
            Err(e) => {
                if attempt == max_retries {
                    return Err(CliError::RegistryTransport {
                        url: url.clone(),
                        source: e,
                    });
                }
                continue;
            }
        };

        let status = res.status();
        if status.is_success() {
            return res.json::<RegistryRuleResponse>().await.map_err(|e| CliError::RegistryTransport {
                url: url.clone(),
                source: e,
            });
        }

        let snippet = res.text().await.unwrap_or_default();
        if status.is_server_error() || status == reqwest::StatusCode::TOO_MANY_REQUESTS {
            if attempt == max_retries {
                return Err(CliError::RegistryHttp {
                    url: url.clone(),
                    status,
                    snippet: truncate(&snippet, 512),
                });
            }
            continue;
        }

        return Err(CliError::RegistryHttp {
            url,
            status,
            snippet: truncate(&snippet, 512),
        });
    }

    unreachable!("retry loop must return");
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max])
    }
}
