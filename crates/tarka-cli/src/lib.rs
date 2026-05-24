//! Library surface for `tarka` CLI (unit-testable replay orchestration).

pub mod clickhouse;
pub mod diff;
pub mod error;
pub mod mock_external;
pub mod registry;
pub mod replay;
pub mod scorecard;
pub mod signals;
pub mod wasm_loader;

#[cfg(feature = "test-helpers")]
pub mod test_helpers;

pub use clickhouse::{
    collect_transaction_ids_from_signal_maps, parse_ground_truth_class,
    transaction_id_from_signal_map, ClickhouseClient, ManifestWindowBookmark, NormalizedLabelRow,
    MANIFEST_BATCH_STREAM_CHUNK,
};
pub use error::CliError;
pub use replay::{
    eprint_batch_replay_field_error, fetch_manifest_batch_by_window, parse_rfc3339_to_unix_ns,
    run_batch_replay, run_forensic_replay, BatchReplayConfig, ForensicReplayConfig,
    MAX_MANIFEST_BATCH_WINDOW_PULL,
};
pub use scorecard::{
    compute_transactions_per_second, BatchReplayScorecardDocument, EvaluatedManifestRecord,
    GroundTruthCrossrefSummary, MismatchCollector, MismatchDetail, ReplayScorecard,
    ScorecardCollector, ScorecardCounterMatrix, ScorecardError, TraceMismatchCapture,
};

#[cfg(feature = "test-helpers")]
pub use test_helpers::{
    decode_evidence_manifest_binary, encode_evidence_manifest_binary, synthesize_manifest_batch,
    synthesize_manifest_test_vector, GroundTruthLabelFixture, ManifestTestVector,
    ManifestTestVectorBuilder, MockClickHouseHarness, TraceStepSpec,
    DEFAULT_TEST_RULE_CONTENT_ID,
};
