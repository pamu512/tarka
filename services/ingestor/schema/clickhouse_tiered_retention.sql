-- =============================================================================
-- Tiered evidence retention — migration / operations SQL
-- =============================================================================
-- Greenfield installs: definitions live in `clickhouse.sql` (decisions table + MV + TTL).
--
-- Use THIS file when upgrading an older cluster that already had `evidence_manifests`
-- without `under_investigation` or tiered TTL. Requires ClickHouse 21.12+ (TTL DELETE WHERE).
--
-- Policy summary:
--   • evidence_manifest_decisions: no trace_json; TTL 730 days (2 years) on event time.
--   • evidence_manifests: full row; DELETE at 90d if under_investigation = 0; all rows cap at 730d.
--   • Set under_investigation = 1 (with lightweight mutation) to keep the full manifest past 90d
--     until the 2-year cap (e.g. legal / fraud investigation).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS tarka_audit;

-- Step A: long-lived table (if not already created by a fresh `clickhouse.sql` deploy)
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

-- Step B: materialized view (idempotent)
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

-- Step C: heavy table — investigation flag + tiered TTL (replace any prior single-rule TTL)
ALTER TABLE tarka_audit.evidence_manifests
    ADD COLUMN IF NOT EXISTS under_investigation UInt8 DEFAULT 0
        COMMENT '1 = retain full manifest past 90d cold rule until max TTL';

ALTER TABLE tarka_audit.evidence_manifests
    MODIFY TTL
        event_ts + INTERVAL 90 DAY DELETE WHERE under_investigation = 0,
        event_ts + INTERVAL 730 DAY DELETE;

-- Step D: backfill decision-tier rows for manifests ingested before the MV existed (idempotent)
INSERT INTO tarka_audit.evidence_manifest_decisions (
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
)
SELECT
    m.tenant_id,
    m.manifest_id,
    m.engine_version,
    m.timestamp_ns,
    m.final_decision,
    m.total_execution_time_us,
    m.signals,
    m.crypto_algorithm,
    m.crypto_signature_hex,
    m.crypto_key_id,
    m.raw_manifest_sha256,
    m.under_investigation,
    m.ingested_at
FROM tarka_audit.evidence_manifests AS m
WHERE (m.tenant_id, m.manifest_id) NOT IN (
    SELECT tenant_id, manifest_id FROM tarka_audit.evidence_manifest_decisions
);

-- Step E (optional): mark a case under investigation — run both UPDATES so heavy + decision rows stay aligned
-- ALTER TABLE tarka_audit.evidence_manifests
--     UPDATE under_investigation = 1 WHERE manifest_id = toUUID('…');
-- ALTER TABLE tarka_audit.evidence_manifest_decisions
--     UPDATE under_investigation = 1 WHERE manifest_id = toUUID('…');
