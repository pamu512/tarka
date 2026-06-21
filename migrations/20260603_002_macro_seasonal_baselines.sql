-- Target: migrations/20260603_002_macro_seasonal_baselines.sql
-- Macro seasonal baselines + HIL override tracking (ClickHouse).
--
-- Daily rollups use AggregatingMergeTree + sumState/sumMerge so concurrent MV
-- inserts for the same (tenant, entity, date) merge correctly (plain UInt32
-- columns with `1 as daily_tx_count` would not aggregate safely on this engine).
--
-- Apply UP only (between UP and DOWN markers), or run DOWN alone to roll back.
--   python scripts/apply_clickhouse_migration.py migrations/20260603_002_macro_seasonal_baselines.sql

-- =============================================================================
-- UP
-- =============================================================================

CREATE DATABASE IF NOT EXISTS tarka_core;

CREATE TABLE IF NOT EXISTS tarka_core.transactions
(
    tenant_id LowCardinality(String),
    created_at DateTime('UTC'),
    entity_id String,
    region_code LowCardinality(String),
    amount_usd Float64,
    status LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, entity_id, created_at)
TTL created_at + INTERVAL 3 YEAR;

CREATE DATABASE IF NOT EXISTS tarka_analytics;

-- 1. Daily Aggregation Table for the 3-Year Matrix
CREATE TABLE IF NOT EXISTS tarka_analytics.daily_entity_rollups
(
    tenant_id LowCardinality(String),
    date Date,
    entity_id String,
    region_code LowCardinality(String),
    day_of_week UInt8,
    day_of_year UInt16,

    daily_tx_count AggregateFunction(sum, UInt64),
    daily_tx_volume_usd AggregateFunction(sum, Float64),
    daily_failed_auth_count AggregateFunction(sum, UInt64)
)
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(date)
PRIMARY KEY (tenant_id, entity_id)
ORDER BY (tenant_id, entity_id, date, region_code, day_of_week, day_of_year)
TTL date + INTERVAL 3 YEAR;

-- 2. Materialized View to feed the Daily Matrix from raw transactions
CREATE MATERIALIZED VIEW IF NOT EXISTS tarka_analytics.mv_daily_entity_rollups
TO tarka_analytics.daily_entity_rollups AS
SELECT
    tenant_id,
    toDate(created_at) AS date,
    entity_id,
    region_code,
    toDayOfWeek(created_at) AS day_of_week,
    toDayOfYear(created_at) AS day_of_year,
    sumState(toUInt64(1)) AS daily_tx_count,
    sumState(amount_usd) AS daily_tx_volume_usd,
    sumState(toUInt64(if(status = 'FAILED_AUTH', 1, 0))) AS daily_failed_auth_count
FROM tarka_core.transactions;

-- Query helper: merge aggregate states into scalars (cascade windows read from here).
CREATE VIEW IF NOT EXISTS tarka_analytics.v_daily_entity_rollups_merged AS
SELECT
    tenant_id,
    date,
    entity_id,
    region_code,
    day_of_week,
    day_of_year,
    sumMerge(daily_tx_count) AS daily_tx_count,
    sumMerge(daily_tx_volume_usd) AS daily_tx_volume_usd,
    sumMerge(daily_failed_auth_count) AS daily_failed_auth_count
FROM tarka_analytics.daily_entity_rollups
GROUP BY
    tenant_id,
    date,
    entity_id,
    region_code,
    day_of_week,
    day_of_year;

-- 3. HIL Context Exclusion & Override Table
CREATE TABLE IF NOT EXISTS tarka_analytics.hil_context_overrides
(
    tenant_id LowCardinality(String),
    entity_id String,
    override_type Enum8(
        'ALLOW_SEASONAL_SPIKE' = 1,
        'FORCE_BLOCK' = 2,
        'TEMPORARY_BASELINE_SHIFT' = 3
    ),
    scope_key String,
    expires_at DateTime,
    created_at DateTime DEFAULT now(),
    analyst_rationale String
)
ENGINE = ReplacingMergeTree(created_at)
PRIMARY KEY (tenant_id, entity_id)
ORDER BY (tenant_id, entity_id, override_type, scope_key);

-- 4. Sub-minute tactical plane (fed by stream ingest; read by macro_synthesizer)
CREATE TABLE IF NOT EXISTS tarka_analytics.sub_minute_metrics
(
    tenant_id LowCardinality(String),
    entity_id String,
    bucket_start DateTime('UTC'),
    tx_count UInt32,
    failed_auth_count UInt32,
    tx_volume_usd Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(bucket_start)
ORDER BY (tenant_id, entity_id, bucket_start)
TTL bucket_start + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;

-- =============================================================================
-- DOWN
-- =============================================================================

DROP TABLE IF EXISTS tarka_analytics.sub_minute_metrics;

DROP VIEW IF EXISTS tarka_analytics.v_daily_entity_rollups_merged;

DROP VIEW IF EXISTS tarka_analytics.mv_daily_entity_rollups;

DROP TABLE IF EXISTS tarka_analytics.daily_entity_rollups;

DROP TABLE IF EXISTS tarka_analytics.hil_context_overrides;

DROP TABLE IF EXISTS tarka_core.transactions;
