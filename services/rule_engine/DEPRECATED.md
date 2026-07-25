# Deprecated HTTP evaluate / AST versioning sidecar

**Status:** archived for evaluate path (Approach A, 2026-07-13).

Orchestrator ingest evaluates via **decision-api** (`RULE_EVAL_BACKEND=decision_api`,
`DECISION_API_URL`). Do not deploy this service for production evaluate.

## Compatibility adapter (one release)

Set both:

- `RULE_ENGINE_COMPAT_MODE=decision_api`
- `DECISION_API_URL` (e.g. `http://decision-api:8000` or `http://core-api:8000/decisions`)

Then:

| Legacy route | Adapter behavior |
|--------------|------------------|
| `POST /v1/evaluate` | Proxies to `{DECISION_API_URL}/v1/decisions/evaluate` (Rust `tarka_rule_engine`) and remaps to `{actions, transaction_id, …}` |
| `POST /v1/rules/reload` | Proxies to `{DECISION_API_URL}/v1/admin/rules/reload` |

Local Python AST evaluation remains the default when `RULE_ENGINE_COMPAT_MODE` is unset
(unit tests / dual-run against the historical evaluator).

**Removal gate:** delete `compat_adapter.py` and the compat branches in `main.py` when
`RULE_EVAL_BACKEND=python`, `RULE_EVAL_DUAL_RUN`, and `RULE_ENGINE_COMPAT_MODE` have
zero runtime callers.

## Still used (in-process) — exile candidates

- **Canonical schemas:** `tarka_shared.ast_schemas` (`packages/shared-core`)
- `rule_engine.ast_schemas` is a **re-export shim** only
- `evaluator` — orchestrator `rule_shadow_test`, pack validators, e2e holy-grail (still under this package)
- Optional compose profile `legacy-python-rules` on `docker-compose.v2-ingest.yml` for dual-run / emergency rollback

Importing this package emits `DeprecationWarning`. Evaluate path of record remains decision-api.

## Parked (not on consolidated path)

| Route | Replacement |
|-------|-------------|
| `POST /v1/evaluate` | `POST {DECISION_API_URL}/v1/decisions/evaluate` (or compat mode above) |
| `POST /v1/rules/deploy`, versions, rollback | Decision-api pack GitOps / `POST /v1/admin/rules/reload` (AST promote UI returns **410**) |
| `POST /v1/hypotheses/deploy` | Redis + NATS watcher path (separate from evaluate) |

Rollback evaluate: set `RULE_EVAL_BACKEND=python` and start this service (`--profile legacy-python-rules`). Prefer compat mode so evaluate still hits decision-api.
