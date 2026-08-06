# Shadow mode, simulation, and A/B rule testing

Tarka separates **live decisions** from **shadow / offline evaluation**:

- **Live:** `POST /v1/decisions/evaluate` — production side effects when not marked shadow.
- **Production shadow (named contract):** same evaluate path with `metadata.shadow: true` — full scoring + audit, **non-mutating** side effects.
- **Offline / synthetic:** `/v1/simulation/*` — labeled scenarios and A/B without production traffic.

## 1. Production shadow contract (`metadata.shadow: true`)

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

When ``metadata.shadow`` is true (see `evaluate_shadow_request.is_shadow_evaluate_request`):

1. Evaluation runs and writes an audit row with ``payload_snapshot.shadow: true`` and tag ``evaluate:shadow``.
2. **Non-mutating side effects:** no Redis aggregate writes, no fingerprint/entity-link writes, no graph upsert, no challenge webhook, no auto case create, no enforcement adapters.
3. Warehouse diff: [`scripts/oss/shadow_vs_primary_diff_recipe.sql`](../../../scripts/oss/shadow_vs_primary_diff_recipe.sql).
4. Promote only when vertical ``promote_gate`` / ``kill_criteria`` allow — prove with:

```bash
python3 scripts/oss/shadow_promote_gate_smoke.py
```

5. Use **`/v1/replay`** with ``trace_ids`` for paired analyst review when replay is enabled.

## 2. Single rule pack run (synthetic)

```bash
curl -s -X POST http://localhost:8000/v1/simulation/run \
  -H "Content-Type: application/json" \
  -d '{"scenario": "bot_attack", "evaluate_rules": true, "include_ml": false}'
```

Response includes **`experiment_guardrails`** — read the **notes** before treating metrics as KPIs.

## 3. A/B two rule sets (same synthetic traffic)

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

## 4. Vertical pack vs baseline

```bash
curl -s -X POST http://localhost:8000/v1/simulation/benchmark/vertical \
  -H "Content-Type: application/json" \
  -d '{"scenario": "high_fraud", "vertical": "fintech"}'
```

Requires a defined pack in **`vertical_packs`** for that key. Promotion uses the same ``kill_criteria`` as the shadow promote smoke.

## 5. Scenarios

`GET /v1/simulation/scenarios` lists built-ins (`baseline`, `high_fraud`, `bot_attack`, `account_takeover`, `money_mule`).
