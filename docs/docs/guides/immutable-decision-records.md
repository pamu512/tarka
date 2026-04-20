# Immutable Decision Records

Tarka writes a canonical decision record for every evaluate call using schema `tarka.decision_log/v1`.

## What is persisted

- `trace_id`, tenant/entity/event identifiers, decision, score, rule hits, tags, reasons.
- Full `inference_context` payload used to explain the decision.
- Challenge policy resolution (`recommended_action`, `challenge_policy_id`, `challenge_metadata`).
- Fallback/degraded-path reason when any dependency was unavailable.
- Masked `payload_snapshot` used for replay and audit.

## OSS storage mode

By default, Decision API appends JSONL records to:

- `DECISION_LOG_PATH` (default: `./data/decision_logs/decision-log.jsonl`)

Config:

- `DECISION_LOG_ENABLED=true|false` (default `true`)
- `DECISION_LOG_PATH=...`

## Warehouse mode (hosted / enterprise)

Decision API can dual-write to a warehouse ingress endpoint:

- `DECISION_LOG_WAREHOUSE_URL=https://...`
- `DECISION_LOG_WAREHOUSE_API_KEY=...` (optional bearer token)

Recommended warehouse table shape:

- Partition keys: `tenant_id`, event date from `logged_at`
- Primary lookup: `trace_id`
- JSON columns: `inference_context`, `payload_snapshot`, `challenge_metadata`

## Replay workflow

Use replay tooling to compare historical decisions with current runtime behavior:

```bash
python scripts/replay/replay_decision_logs.py \
  --input ./data/decision_logs/decision-log.jsonl \
  --base-url http://localhost:8000 \
  --api-key "$API_KEY"
```

This outputs decision-change rate for regression checks after rule/model updates.
