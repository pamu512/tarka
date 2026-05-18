//! Library surface for `tarka` CLI (unit-testable replay orchestration).

pub mod clickhouse;
pub mod diff;
pub mod error;
pub mod mock_external;
pub mod registry;
pub mod replay;
pub mod signals;
pub mod wasm_loader;

pub use error::CliError;
pub use replay::{run_forensic_replay, ForensicReplayConfig};
