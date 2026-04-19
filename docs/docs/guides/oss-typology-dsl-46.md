# Typology DSL + predicate registry (OSS #46)

Builds on the typology layer (OSS #34) with **named, reusable predicates** and **version pinning**.

## Files

| File | Role |
|------|------|
| `services/decision-api/rules/typology_predicate_registry_v1.json` | Registry id + version + list of `{ id, description, when }` (`when` uses the same `field` / `op` / `value` shape as JSON rules). |
| `services/decision-api/rules/typology_definitions_v1.json` | `dsl_version`, **`predicate_registry_pin`** (must equal registry `version`), typologies with `feature_predicates` using **`predicate_ref`** or legacy inline `field`/`op`/`value`. |

## Evaluation

- **`predicate_ref`** resolves `when` from the registry and applies **`bonus`** from the typology line.
- If **`predicate_registry_pin` ≠ registry `version`**, `predicate_ref` predicates are **skipped** (safe rollout: bump registry + definitions together).
- Each typology result includes **`dsl_version`** and **`predicate_registry`** `{ registry_id, version, pin, pin_match }` for audit.

## API

- **`GET /v1/admin/typology/predicate-registry`** — public catalog (reload with **`POST /v1/admin/rules/reload`**).

## CI

- `python scripts/policy/validate_typology_dsl.py` — pins match, every `predicate_ref` exists.
