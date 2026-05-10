"""
ClickHouse DDL for persisting **wire-format** verification outcomes (no legacy column names).

Use these identifiers when ingesting auditor results alongside upstream evidence pipelines.
"""

from __future__ import annotations

# Wire-native field names only — mirrors ``proto/tarka/evidence/wire/v1/evidence.proto`` / ingestor row keys.
VERIFICATION_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS tarka_verifier_events (
    ingested_at DateTime64(3) DEFAULT now64(3),

    manifest_id String,
    occurred_at_unix_ns UInt64,

    engine_version String,
    engine_git_hash String,
    engine_environment String,
    engine_instance_id String,

    verdict_action String,
    verdict_score Float64,
    verdict_latency_ns UInt64,

    merkle_root FixedString(32),
    signature FixedString(64),
    merkle_proof String,

    verification_ok UInt8,
    sealed_merkle_root_hex String,
    trace_inner_root_hex String,
    trace_leaf_count UInt32,
    manifest_integrity_reason LowCardinality(String),
    failure_codes Array(String),

    manifest_sha256 FixedString(32)
)
ENGINE = MergeTree
ORDER BY (ingested_at, manifest_id);
"""
