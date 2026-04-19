# Policy DAG (OSS #31): canary, shadow, champion–challenger

This guide maps [GitHub issue #31](https://github.com/pamu512/tarka/issues/31) (borrowed-from-OSS) to **what Tarka implements today** and how to operate it.

## Canary (stable cohort + traffic %)

JSON rule packs support `**canary_percent`** (0–100) and optional `**effective_at**`. For each pack, the Decision API computes a **stable 0..99 bucket**:

```text
SHA256("{tenant_id}|{entity_id}|{pack_key}")[:8] mod 100
```

where `pack_key` is the rule file name or pack `name`. The pack applies in **production** only when `bucket < canary_percent` (and `effective_at` has passed). Same entity always gets the same bucket for a given pack key.

- **Implementation:** `services/decision-api/src/decision_api/json_rules.py` (`_pack_experiment_bucket`, `_pack_should_apply`).
- **Simulation** (`evaluation_mode=simulation`) skips canary gating so offline runs see full rule effects.

## Shadow (does not change production decision)

Shadow rule packs (`mode: shadow` on disk, or `SHADOW_RULES_PATH`) are evaluated **after** the production decision. Results are logged and can be published to NATS; they **do not** change the response `decision` / `score`.

- **Implementation:** `services/decision-api/src/decision_api/shadow.py`, `_run_shadow_evaluation` in `main.py`.
- **API:** `GET /v1/rules/shadow/observations`, `GET /v1/rules/shadow/stats`.

## Champion–challenger (audit-only analysis)

When `**POLICY_CHAMPION_CHALLENGER_ENABLED=true`**, the API runs a second JSON rule pass with `**evaluation_mode=challenger**`: all active packs that pass `**effective_at**` are evaluated **ignoring `canary_percent`**. That produces a **challenger** rule-score delta comparable to the **champion** (production canary) path.

Both paths share the same **OPA delta**, consortium/graph/replay additions, and thresholds for a **rule-only** `allow` / `review` / `deny` comparison. The **HTTP response is unchanged** (still production scoring + ML blend). Structured comparison is stored on the audit row under `**payload_snapshot.policy_routing`**.


| Field                                           | Meaning                                                               |
| ----------------------------------------------- | --------------------------------------------------------------------- |
| `cohort_bucket_0_99`                            | Stable bucket for dashboards (`POLICY_COHORT_SALT` + tenant + entity) |
| `champion_rule_score` / `challenger_rule_score` | Rule-era scores before ML blend                                       |
| `champion_decision` / `challenger_decision`     | Thresholded from rule scores only                                     |
| `decisions_agree`                               | Boolean                                                               |
| `ml_score`                                      | ML score if present (for offline joins)                               |


- **Helpers:** `services/decision-api/src/decision_api/policy_routing.py`
- **Env:** `POLICY_CHAMPION_CHALLENGER_ENABLED`, `POLICY_COHORT_SALT` (default `policy_v1`)

## Routing priority (issue acceptance)

Documented **Tarka equivalent**:

1. **Production** decision uses champion JSON rules (canary-gated) + OPA + ML blend + thresholds.
2. **Shadow** never overrides (1).
3. **Challenger** is **audit-only** and does not override (1).

For strict “canary > AB > main” tables from risk-engine YAML, continue to use **per-pack `canary_percent`** and separate packs rather than a single global A/B flag.

## References

- [OSS ship order](./oss-ship-order-dependencies.md) (issue #31 dependencies)
- [Counter replay parity](./counter-replay-parity.md) (separate Epic C track)

