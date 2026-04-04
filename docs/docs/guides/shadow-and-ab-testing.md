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

## 4. Production “shadow” pattern (conceptual)

1. **Duplicate** ingress traffic to a **non-mutating** path (e.g. async worker calling evaluate with **`metadata.shadow: true`** if you add that convention).
2. Compare **shadow** decisions to **primary** in your warehouse; do **not** block users on shadow outcomes until promoted.
3. Use **`/v1/replay`** with **`trace_ids`** for paired analyst review when replay is enabled (see decision-api tests and OpenAPI).

## 5. Scenarios

`GET /v1/simulation/scenarios` lists built-ins (`baseline`, `high_fraud`, `bot_attack`, `account_takeover`, `money_mule`).
