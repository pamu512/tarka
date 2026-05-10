-- OpenTelemetry trace spans for forensic querying (ClickHouse exporter — traces pipeline).
--
-- Schema matches opentelemetry-collector-contrib `clickhouseexporter` INSERT columns
-- (see traces_insert.sql / traces_table.sql in that repo). Table name `otel_spans` is wired via
-- deploy/otel-collector-config.yaml `traces_table_name`.
--
-- Apply after `CREATE DATABASE tarka_audit` (clickhouse.sql). Start otel-collector with
-- `create_schema: false` so this file remains the source of truth.
--
-- Example: spans for one trace (uses lookup table for time bounds — same pattern as upstream docs).
--   WITH
--     '<32-hex trace id>' AS tid,
--     (SELECT min(Start) FROM tarka_audit.otel_spans_trace_id_ts WHERE TraceId = tid) AS t0,
--     (SELECT max(End) + 1 FROM tarka_audit.otel_spans_trace_id_ts WHERE TraceId = tid) AS t1
--   SELECT Timestamp, TraceId, SpanId, ParentSpanId, SpanName, ServiceName, Duration, StatusCode
--   FROM tarka_audit.otel_spans
--   WHERE TraceId = tid AND Timestamp >= t0 AND Timestamp <= t1
--   ORDER BY Timestamp;

CREATE TABLE IF NOT EXISTS tarka_audit.otel_spans
(
    Timestamp DateTime64(9) CODEC(Delta, ZSTD(1)),
    TraceId String CODEC(ZSTD(1)),
    SpanId String CODEC(ZSTD(1)),
    ParentSpanId String CODEC(ZSTD(1)),
    TraceState String CODEC(ZSTD(1)),
    SpanName LowCardinality(String) CODEC(ZSTD(1)),
    SpanKind LowCardinality(String) CODEC(ZSTD(1)),
    ServiceName LowCardinality(String) CODEC(ZSTD(1)),
    ResourceAttributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    ScopeName String CODEC(ZSTD(1)),
    ScopeVersion String CODEC(ZSTD(1)),
    SpanAttributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    Duration UInt64 CODEC(ZSTD(1)),
    StatusCode LowCardinality(String) CODEC(ZSTD(1)),
    StatusMessage String CODEC(ZSTD(1)),
    Events Nested(
        Timestamp DateTime64(9),
        Name LowCardinality(String),
        Attributes Map(LowCardinality(String), String)
    ) CODEC(ZSTD(1)),
    Links Nested(
        TraceId String,
        SpanId String,
        TraceState String,
        Attributes Map(LowCardinality(String), String)
    ) CODEC(ZSTD(1)),
    INDEX idx_trace_id TraceId TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_res_attr_key mapKeys(ResourceAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_res_attr_value mapValues(ResourceAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_span_attr_key mapKeys(SpanAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_span_attr_value mapValues(SpanAttributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_duration Duration TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
PARTITION BY toDate(Timestamp)
ORDER BY (ServiceName, SpanName, toDateTime(Timestamp))
TTL Timestamp + toIntervalDay(400) DELETE
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS tarka_audit.otel_spans_trace_id_ts
(
    TraceId String CODEC(ZSTD(1)),
    Start DateTime CODEC(Delta, ZSTD(1)),
    End DateTime CODEC(Delta, ZSTD(1)),
    INDEX idx_trace_id TraceId TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = MergeTree()
PARTITION BY toDate(Start)
ORDER BY (TraceId, Start)
TTL Start + toIntervalDay(400) DELETE
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS tarka_audit.otel_spans_trace_id_ts_mv TO tarka_audit.otel_spans_trace_id_ts
AS
SELECT
    TraceId,
    toDateTime(min(Timestamp)) AS Start,
    toDateTime(max(Timestamp)) AS End
FROM tarka_audit.otel_spans
WHERE TraceId != ''
GROUP BY TraceId;
