# Inference Track B — S9 loyalty feed effectiveness (CI)

Date: 2026-08-06  
Status: approved (program: A → B → A+B)  
Depends: Track A (ECE CI) already landed

## Goal

Prove with durable CI evidence that **complete** hygiene feeds + program config produce multi-gate loyalty economics (`eligible` bool), and **incomplete** feeds never yield `eligible: true`. Evaluate path already attaches gates without deny.

## Non-goals

- Live tenant warehouse feeds  
- Claiming Inference **4.5** (reserved for A+B claim step)  
- Ordering deny from loyalty path

## Design

1. Fixture pack under `scripts/oss/fixtures/loyalty_economics_cases.json` (abuse / healthy / incomplete).  
2. `scripts/oss/loyalty_economics_feed_smoke.py` — pure engine, fixed `now`, assert cases.  
3. CI `audit-stubs` step.  
4. Update prerequisites “Current gap” honesty table.  
5. Regrade Inference ~**4.2** Could-be-better after B; **4.5** only on A+B.
