-- =============================================================================
-- Audit analytics: Materialized Views for "Decision Consistency" / logic drift
-- =============================================================================
-- Prerequisites: `tarka_audit.evidence_manifests` with `tenant_id` (see clickhouse.sql).
--
-- Multi-tenant: aggregate keys include `tenant_id` so Environment A drift analytics never
-- merge with Environment B. After schema upgrades, DROP dependent MVs before ALTER TABLE,
-- or recreate destination tables on empty clusters.
--
-- Query pattern:
--   SELECT * FROM tarka_audit.v_audit_logic_drift_live WHERE tenant_id = 'env-a';
--
-- ClickHouse 23.8+ recommended (consistent with evidence_manifests JSON column).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS tarka_audit;

-- -----------------------------------------------------------------------------
-- AggregatingMergeTree destination: rolling aggregate states per tenant/day/subject/inputs/engine
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tarka_audit.mv_decision_consistency_by_input_agg
(
    tenant_id LowCardinality(String),
    day Date,
    user_key String COMMENT 'Resolved from signals[user_id|entity_id|subject_id] or anonymous',
    input_fingerprint UInt64 COMMENT 'sipHash64 over sorted k=v pairs of signals (canonical input identity)',
    engine_version LowCardinality(String),
    decision_distinct AggregateFunction(uniqExact, UInt8) COMMENT 'Distinct final_decision values observed',
    eval_count AggregateFunction(count) COMMENT 'Rows merged into this aggregate group',
    last_ingested_at AggregateFunction(max, DateTime64(3, 'UTC'))
)
ENGINE = AggregatingMergeTree()
PARTITION BY (tenant_id, toYYYYMM(day))
ORDER BY (tenant_id, day, engine_version, user_key, input_fingerprint)
TTL day + toIntervalDay(400)
SETTINGS index_granularity = 8192;

-- -----------------------------------------------------------------------------
-- Materialized view: ingest path pushes each evidence row into the agg table
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS tarka_audit.mv_decision_consistency_by_input_mv
TO tarka_audit.mv_decision_consistency_by_input_agg
AS
SELECT
    tenant_id,
    toDate(ingested_at) AS day,
    multiIf(
        coalesce(mapGet(signals, 'user_id'), '') != '',
        mapGet(signals, 'user_id'),
        coalesce(mapGet(signals, 'entity_id'), '') != '',
        mapGet(signals, 'entity_id'),
        coalesce(mapGet(signals, 'subject_id'), '') != '',
        mapGet(signals, 'subject_id'),
        '__anonymous__'
    ) AS user_key,
    sipHash64(
        arrayStringConcat(
            arrayMap(
                k -> concat(k, '=', coalesce(mapGet(signals, k), '')),
                arraySort(mapKeys(signals))
            ),
            '\x01'
        )
    ) AS input_fingerprint,
    engine_version,
    uniqExactState(final_decision) AS decision_distinct,
    countState() AS eval_count,
    maxState(ingested_at) AS last_ingested_at
FROM tarka_audit.evidence_manifests;

-- -----------------------------------------------------------------------------
-- UI-facing view: rows where more than one distinct decision appeared (live drift)
-- -----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS tarka_audit.v_audit_logic_drift_live
AS
SELECT
    tenant_id,
    day,
    engine_version,
    user_key,
    input_fingerprint,
    distinct_final_decisions,
    evaluation_rows,
    last_seen_at
FROM
(
    SELECT
        tenant_id,
        day,
        engine_version,
        user_key,
        input_fingerprint,
        uniqExactMerge(decision_distinct) AS distinct_final_decisions,
        countMerge(eval_count) AS evaluation_rows,
        maxMerge(last_ingested_at) AS last_seen_at
    FROM tarka_audit.mv_decision_consistency_by_input_agg
    GROUP BY
        tenant_id,
        day,
        engine_version,
        user_key,
        input_fingerprint
)
WHERE distinct_final_decisions > 1;

-- -----------------------------------------------------------------------------
-- Optional: hourly rollup for denser real-time dashboards (same agg semantics)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tarka_audit.mv_decision_consistency_by_hour_agg
(
    tenant_id LowCardinality(String),
    hour DateTime,
    user_key String,
    input_fingerprint UInt64,
    engine_version LowCardinality(String),
    decision_distinct AggregateFunction(uniqExact, UInt8),
    eval_count AggregateFunction(count),
    last_ingested_at AggregateFunction(max, DateTime64(3, 'UTC'))
)
ENGINE = AggregatingMergeTree()
PARTITION BY (tenant_id, toYYYYMM(toDate(hour)))
ORDER BY (tenant_id, hour, engine_version, user_key, input_fingerprint)
TTL toDate(hour) + toIntervalDay(400)
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS tarka_audit.mv_decision_consistency_by_hour_mv
TO tarka_audit.mv_decision_consistency_by_hour_agg
AS
SELECT
    tenant_id,
    toStartOfHour(ingested_at) AS hour,
    multiIf(
        coalesce(mapGet(signals, 'user_id'), '') != '',
        mapGet(signals, 'user_id'),
        coalesce(mapGet(signals, 'entity_id'), '') != '',
        mapGet(signals, 'entity_id'),
        coalesce(mapGet(signals, 'subject_id'), '') != '',
        mapGet(signals, 'subject_id'),
        '__anonymous__'
    ) AS user_key,
    sipHash64(
        arrayStringConcat(
            arrayMap(
                k -> concat(k, '=', coalesce(mapGet(signals, k), '')),
                arraySort(mapKeys(signals))
            ),
            '\x01'
        )
    ) AS input_fingerprint,
    engine_version,
    uniqExactState(final_decision) AS decision_distinct,
    countState() AS eval_count,
    maxState(ingested_at) AS last_ingested_at
FROM tarka_audit.evidence_manifests;

-- -----------------------------------------------------------------------------
-- Backfill (run once after deploying MVs; uncomment and execute manually)
-- -----------------------------------------------------------------------------
/*
INSERT INTO tarka_audit.mv_decision_consistency_by_input_agg
SELECT
    tenant_id,
    toDate(ingested_at) AS day,
    multiIf(
        coalesce(mapGet(signals, 'user_id'), '') != '',
        mapGet(signals, 'user_id'),
        coalesce(mapGet(signals, 'entity_id'), '') != '',
        mapGet(signals, 'entity_id'),
        coalesce(mapGet(signals, 'subject_id'), '') != '',
        mapGet(signals, 'subject_id'),
        '__anonymous__'
    ) AS user_key,
    sipHash64(
        arrayStringConcat(
            arrayMap(
                k -> concat(k, '=', coalesce(mapGet(signals, k), '')),
                arraySort(mapKeys(signals))
            ),
            '\x01'
        )
    ) AS input_fingerprint,
    engine_version,
    uniqExactState(final_decision) AS decision_distinct,
    countState() AS eval_count,
    maxState(ingested_at) AS last_ingested_at
FROM tarka_audit.evidence_manifests;

INSERT INTO tarka_audit.mv_decision_consistency_by_hour_agg
SELECT
    tenant_id,
    toStartOfHour(ingested_at) AS hour,
    multiIf(
        coalesce(mapGet(signals, 'user_id'), '') != '',
        mapGet(signals, 'user_id'),
        coalesce(mapGet(signals, 'entity_id'), '') != '',
        mapGet(signals, 'entity_id'),
        coalesce(mapGet(signals, 'subject_id'), '') != '',
        mapGet(signals, 'subject_id'),
        '__anonymous__'
    ) AS user_key,
    sipHash64(
        arrayStringConcat(
            arrayMap(
                k -> concat(k, '=', coalesce(mapGet(signals, k), '')),
                arraySort(mapKeys(signals))
            ),
            '\x01'
        )
    ) AS input_fingerprint,
    engine_version,
    uniqExactState(final_decision) AS decision_distinct,
    countState() AS eval_count,
    maxState(ingested_at) AS last_ingested_at
FROM tarka_audit.evidence_manifests;
*/
