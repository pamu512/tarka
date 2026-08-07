# Track B1+B2 Report — Marketplace COD pack + loyalty-abuse bridge

**Date:** 2026-08-07  
**Status:** DONE  
**Base:** master

## B1 — offline_payment pack + features

| Item | Path / detail |
|------|----------------|
| Feature wiring | `services/decision-api/src/decision_api/offline_payment_features.py` — `payment_method`, `is_cod`, `is_offline_payment` from payload/metadata; bool overrides on `metadata.is_cod` / `metadata.is_offline_payment` |
| Pipeline hook | `services/decision-api/src/decision_api/evaluate/pipeline.py` — called after amount normalization |
| Vertical pack | `services/decision-api/src/decision_api/vertical_packs.py` — `_PACKS["offline_payment"]` with 5 rules |
| Pack tags | `vertical:offline_payment`, `risk:cod_abuse`, `risk:address_hop`, `action:payout_hold` |
| Catalog test | `tests/test_marketplace_vertical_packs.py` — `offline_payment` in `REQUIRED`; kill-gate parametrized |
| Feature tests | `tests/test_offline_payment_features.py` — COD / store_pickup / metadata overrides |

## B2 — loyalty_abuse_bridge

| Item | Path / detail |
|------|----------------|
| Bridge module | `services/decision-api/src/decision_api/loyalty_abuse_bridge.py` |
| Trigger | `metadata.checkpoint=redeem` OR `event_type=redeem` |
| HTTP | `POST {loyalty_abuse_url}/v1/evaluate` Bearer `loyalty_abuse_api_key` |
| Friction tags | `loyalty:friction:{allow\|throttle\|soft_challenge\|hard_challenge\|block}` (allow → none) |
| Fail-soft | exceptions logged; `metrics_inc("loyalty_abuse_bridge_failed")` |
| Config | `config.py`: `loyalty_abuse_url`, `loyalty_abuse_api_key` |
| Wiring | `decision_outcome.schedule_decision_outcomes` + `evaluate/pipeline.py` settings pass-through |
| Tests | `tests/test_loyalty_abuse_bridge.py` — MockTransport POST on redeem; skip when URL empty |

## Constraints verified

- No loyalty-abuse multi_gate import
- No forged LIVE partner pins
- Evaluate response not blocked on bridge failure (background task, fail-soft)

## Tests

```bash
cd services/decision-api && PYTHONPATH=src python3 -m pytest \
  tests/test_offline_payment_features.py \
  tests/test_loyalty_abuse_bridge.py \
  tests/test_marketplace_vertical_packs.py::test_marketplace_verticals_listed_with_rule_floor \
  -q
# 13 passed
```

Install-endpoint async tests in `test_marketplace_vertical_packs.py` require full app deps (`decision_api.main`); catalog floor test passes standalone.

## Env

```
LOYALTY_ABUSE_URL=https://loyalty-abuse.example
LOYALTY_ABUSE_API_KEY=...
```

(Pydantic fields: `loyalty_abuse_url`, `loyalty_abuse_api_key` — map via settings env if wired in deployment.)
