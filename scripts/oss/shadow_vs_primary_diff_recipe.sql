-- Shadow vs primary decision diff (warehouse / ClickHouse-style).
-- Assumes decision_audit (or export) with tags / payload_snapshot.shadow.
-- Adjust table/column names to your sink.

-- Primary decisions (not shadow)
WITH primary AS (
  SELECT
    tenant_id,
    entity_id,
    event_type,
    decision AS primary_decision,
    score AS primary_score,
    trace_id AS primary_trace_id,
    created_at
  FROM decision_audit
  WHERE tenant_id = {tenant_id:String}
    AND (
      NOT has(tags, 'evaluate:shadow')
      AND coalesce(JSONExtractBool(payload_snapshot, 'shadow'), 0) = 0
    )
),
shadow AS (
  SELECT
    tenant_id,
    entity_id,
    event_type,
    decision AS shadow_decision,
    score AS shadow_score,
    trace_id AS shadow_trace_id,
    created_at
  FROM decision_audit
  WHERE tenant_id = {tenant_id:String}
    AND (
      has(tags, 'evaluate:shadow')
      OR coalesce(JSONExtractBool(payload_snapshot, 'shadow'), 0) = 1
    )
)
SELECT
  p.entity_id,
  p.event_type,
  p.primary_decision,
  s.shadow_decision,
  p.primary_score,
  s.shadow_score,
  p.primary_trace_id,
  s.shadow_trace_id,
  p.created_at AS primary_at,
  s.created_at AS shadow_at
FROM primary p
INNER JOIN shadow s
  ON p.tenant_id = s.tenant_id
 AND p.entity_id = s.entity_id
 AND p.event_type = s.event_type
 AND abs(dateDiff('second', p.created_at, s.created_at)) <= 120
WHERE p.primary_decision != s.shadow_decision
ORDER BY p.created_at DESC
LIMIT 500;

-- Aggregate disagreement rate (same window join idea):
-- COUNT(disagree) / COUNT(joined pairs). Promote only when vertical
-- promote_gate / kill_criteria allow — see scripts/oss/shadow_promote_gate_smoke.py
