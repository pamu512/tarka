//! Shared error surface for cross-crate replay and audit operations.

use thiserror::Error;

/// Core engine errors surfaced to CLIs and batch replay orchestrators.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum TarkaCoreError {
    #[error("tenant_id must be a non-empty string")]
    EmptyTenantId,

    #[error("invalid replay window: start_ts ({start}) must be <= end_ts ({end})")]
    InvalidWindow { start: i64, end: i64 },

    #[error("replay window start_ts must be non-negative, got {0}")]
    NegativeWindowStart(i64),

    #[error(
        "manifest batch window returned {count} rows, exceeding memory-safe cap {cap} per pull block"
    )]
    BatchWindowCapExceeded { count: usize, cap: usize },

    #[error("invalid manifest_id UUID `{0}`")]
    InvalidManifestId(String),

    #[error("ClickHouse query failed: {0}")]
    ClickHouse(String),

    #[error("evidence manifest row decode failed: {0}")]
    ManifestDecode(String),
}
