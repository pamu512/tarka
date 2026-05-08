//! Typed errors for forensic replay (no bare `anyhow` at boundaries).

use std::path::PathBuf;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum CliError {
    #[error("invalid ClickHouse identifier `{value}` for {context}: allow ASCII alphanumeric and underscore only")]
    InvalidIdentifier {
        context: &'static str,
        value: String,
    },

    #[error("ClickHouse request failed after retries: {source}")]
    ClickHouseTransport {
        #[source]
        source: reqwest::Error,
    },

    #[error("ClickHouse returned HTTP {status}: body_snippet={snippet:?}")]
    ClickHouseHttp {
        status: reqwest::StatusCode,
        snippet: String,
    },

    #[error("ClickHouse returned unexpected payload: {reason}")]
    ClickHousePayload { reason: String },

    #[error("ClickHouse HTTP request timed out after {0:?}")]
    ClickHouseTimeout(std::time::Duration),

    #[error("no evidence_manifests row for manifest_id={0}")]
    ManifestNotFound(uuid::Uuid),

    #[error("rule resolution failed: {0}")]
    RuleResolution(String),

    #[error("registry GET failed after retries for `{url}`: {source}")]
    RegistryTransport {
        url: String,
        #[source]
        source: reqwest::Error,
    },

    #[error("registry returned HTTP {status} for `{url}` body_snippet={snippet:?}")]
    RegistryHttp {
        url: String,
        status: reqwest::StatusCode,
        snippet: String,
    },

    #[error("failed to read rule file `{path}`: {source}")]
    RuleFileIo {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },

    #[error("rule JSON decode error: {source}")]
    RuleJson {
        #[from]
        source: serde_json::Error,
    },

    #[error("tarka-core integrity or evaluation error: {0}")]
    Core(String),

    #[error("replay evaluation produced PartialManifest: {message} rule={rule_id:?}")]
    PartialReplay {
        message: String,
        rule_id: Option<String>,
    },

    #[error("wasm modules missing for replay (provide --wasm-dir with `<hex>.wasm` artifacts): {0}")]
    WasmMissing(String),
}
