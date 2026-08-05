# Shadow mode, simulation, and A/B rule testing

Tarka separates **live decisions** from **offline evaluation**:

- **Live:** `POST /v1/decisions/evaluate` (and audit APIs) — affects production only when wired to real traffic.
- **Offline / shadow:** **`/v1/simulation/*`** — synthetic labeled scenarios, rule overrides, and vertical-pack comparison **without** storing production audits for those synthetic rows unless you choose to log them separately.

## 1. Single rule pack run

```bash
curl -s -X POST http://localhost:8000/v1/simulation/run \
  -H "Content-Type: application/json" \
  -d '{"scenario": "bot_attack", "evaluate_rules": true, "include_ml": false}'
```

Response includes **`experiment_guardrails`** — read the **notes** before treating metrics as KPIs.

## 2. A/B two rule sets (same synthetic traffic)

```bash
curl -s -X POST http://localhost:8000/v1/simulation/ab-test \
  -H "Content-Type: application/json" \
  -d '{
    "scenario": "baseline",
    "rule_set_a": [],
    "rule_set_b": [
      {"id": "high_amount", "when": [{"field": "amount", "op": "gte", "value": 5000}], "score_delta": 25, "tags": ["high_ticket"]}
    ]
  }'
```

Inspect **`comparison`** (`precision_delta`, `recall_delta`, `f1_delta`, …).

## 3. Vertical pack vs baseline

```bash
curl -s -X POST http://localhost:8000/v1/simulation/benchmark/vertical \
  -H "Content-Type: application/json" \
  -d '{"scenario": "high_fraud", "vertical": "fintech"}'
```

Requires a defined pack in **`vertical_packs`** for that key.

## 4. Production shadow pattern (`metadata.shadow: true`)

Ship convention (decision-api evaluate pipeline):

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "event_type": "payment",
    "entity_id": "u-shadow-1",
    "payload": {"amount": 42},
    "metadata": {"shadow": true}
  }'
```

When ``metadata.shadow`` is true:

1. Evaluation still runs and writes an audit row with ``payload_snapshot.shadow: true`` and tag ``evaluate:shadow`` (warehouse-comparable).
2. **Non-mutating side effects:** no Redis aggregate writes, no fingerprint/entity-link writes, no graph upsert, no challenge webhook, no auto case create, no enforcement adapters.
3. Compare shadow vs primary decisions in ClickHouse/warehouse on ``trace_id`` / entity; promote only when vertical ``promote_gate`` / experiment kill criteria allow.
4. Use **`/v1/replay`** with ``trace_ids`` for paired analyst review when replay is enabled.

## 5. Scenarios

`GET /v1/simulation/scenarios` lists built-ins (`baseline`, `high_fraud`, `bot_attack`, `account_takeover`, `money_mule`).
