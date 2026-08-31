# Observe (shadow mode), simulation, and A/B rule testing

Tarka separates **live decisions** from **observe-only evaluate** and offline simulation. In this guide, **shadow mode** means **Observe** — evaluate with no live side effects — not the LLM sidecar (Advise).

Desk: `/ops/shadow` is always-on lean (not behind an empty signals URL). The leftover card is leftover **cost** + leftover-extra **helpfulness**. **Live rule slip** names a live `rule_id` when fire-rate or hit-mix shifts; a host shadow parks only when exactly one of retire / successor has support. GET `shadow-promote-gate` does not write packs. Promote does not strip the live rule. Scout cannot clobber a slip draft (`409 slip_draft_exists`).

- **Live:** `POST /v1/decisions/evaluate` — production side effects when not marked observe.
- **Observe (named contract):** same evaluate path with `metadata.shadow: true` — full scoring + audit, **non-mutating** side effects.
- **Offline / synthetic:** `/v1/simulation/*` — labeled scenarios and A/B without production traffic.

## 1. Observe contract (`metadata.shadow: true`)

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

## 6. Observe-only pack canary (not Flagger)

Issue #150 progressive rule delivery is **observe-only** on `POST /v1/decisions/evaluate` in this slice — not Flagger, not Argo, and **not** a live verdict flip. Decision-api / the Rust JSON AST remains the sole allow/deny engine.

Set via env (Helm `coreApi.extraEnv` is fine; there is no new Helm key):

- `PACK_CANARY_PERCENT` — default `0` (off). A deterministic tenant+entity bucket selects that fraction of traffic.
- `PACK_CANARY_PACK_ID` — pack `id` / `name` / filename under `RULES_PATH`, **or** `PACK_CANARY_PATH` — a candidate JSON pack file.

When percent is `0`, evaluate does no candidate work. When percent is `>0` and the candidate pack is missing, evaluate **fail-closes** (`503 pack_canary_candidate_missing`) instead of silently scoring live-only while claiming canary. Header `x-tarka-pack-canary: 1` forces the candidate on a single request (desk/QA).

The candidate pack is evaluated through the same JSON/Rust engine and recorded on the audit snapshot (`payload_snapshot.pack_canary`) plus the existing shadow observation log. **Allow/deny returned to the caller still comes only from the live pack.** Percent-based promote of the candidate verdict is a later slice.
