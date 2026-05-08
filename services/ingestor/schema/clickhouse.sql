-- Tarka audit sink — ClickHouse DDL (multi-tenant + tiered retention)
-- Requires ClickHouse 23.8+ for native JSON column on `trace_json` (see notes below).
-- OpenTelemetry span storage (forensic traces): see `clickhouse_otel_spans.sql` + deploy/otel-collector-config.yaml.
--
-- Partitioning: (tenant_id, toYYYYMM(event_ts)) enables DROP PARTITION per tenant/month.
--
-- Tiered retention (TTL):
--   • evidence_manifest_decisions: decision payload without trace_json — TTL 730 days (~2 years).
--   • evidence_manifests: full row incl. trace_json — deleted after 90 days unless under_investigation;
--     maximum age 730 days for all rows. Populates decisions via materialized view on insert.

CREATE DATABASE IF NOT EXISTS tarka_audit;

-- Primary evidence table: one row per ingested EvidenceManifest (protobuf); holds heavy `trace_json`.
CREATE TABLE IF NOT EXISTS tarka_audit.evidence_manifests
(
    tenant_id LowCardinality(String),
    manifest_id UUID,
    engine_version LowCardinality(String),
    timestamp_ns UInt64,
    event_ts DateTime64(3, 'UTC') MATERIALIZED toDateTime64(timestamp_ns / 1000000000, 3, 'UTC'),
    final_decision UInt8,
    total_execution_time_us UInt64,
    signals Map(String, String),
    trace_json JSON,
    crypto_algorithm LowCardinality(String),
    crypto_signature_hex String,
    crypto_key_id String,
    raw_manifest_sha256 FixedString(32),
    under_investigation UInt8 DEFAULT 0
        COMMENT '1 = retain full manifest past 90d until max TTL (investigation / legal hold)',
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_ts))
ORDER BY (tenant_id, event_ts, manifest_id)
TTL
    event_ts + INTERVAL 90 DAY DELETE WHERE under_investigation = 0,
    event_ts + INTERVAL 730 DAY DELETE
SETTINGS index_granularity = 8192;

-- Decision-tier retention (no execution trace): fed automatically by MV from evidence_manifests.
CREATE TABLE IF NOT EXISTS tarka_audit.evidence_manifest_decisions
(
    tenant_id LowCardinality(String),
    manifest_id UUID,
    engine_version LowCardinality(String),
    timestamp_ns UInt64,
    event_ts DateTime64(3, 'UTC') MATERIALIZED toDateTime64(timestamp_ns / 1000000000, 3, 'UTC'),
    final_decision UInt8,
    total_execution_time_us UInt64,
    signals Map(String, String),
    crypto_algorithm LowCardinality(String),
    crypto_signature_hex String,
    crypto_key_id String,
    raw_manifest_sha256 FixedString(32),
    under_investigation UInt8 DEFAULT 0,
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(event_ts))
ORDER BY (tenant_id, event_ts, manifest_id)
TTL event_ts + INTERVAL 730 DAY DELETE
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS tarka_audit.mv_evidence_manifest_to_decisions
TO tarka_audit.evidence_manifest_decisions
AS
SELECT
    tenant_id,
    manifest_id,
    engine_version,
    timestamp_ns,
    final_decision,
    total_execution_time_us,
    signals,
    crypto_algorithm,
    crypto_signature_hex,
    crypto_key_id,
    raw_manifest_sha256,
    under_investigation,
    ingested_at
FROM tarka_audit.evidence_manifests;

-- Batch anchoring: homogeneous batches per tenant (ingestor isolates Redis lists by tenant_id).
CREATE TABLE IF NOT EXISTS tarka_audit.audit_anchors
(
    tenant_id LowCardinality(String),
    batch_seq UInt64,
    batch_root_hex String,
    manifest_count UInt32,
    first_manifest_id UUID,
    last_manifest_id UUID,
    first_leaf_sha256_hex String,
    last_leaf_sha256_hex String,
    anchored_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(anchored_at))
ORDER BY (tenant_id, anchored_at, batch_seq);
