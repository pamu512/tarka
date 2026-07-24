# Deprecated HTTP evaluate / AST versioning sidecar

**Status:** archived for evaluate path (Approach A, 2026-07-13).

Orchestrator ingest evaluates via **decision-api** (`RULE_EVAL_BACKEND=decision_api`,
`DECISION_API_URL`). Do not deploy this service for production evaluate.

## Still used (in-process) — exile candidates

- **Canonical schemas:** `tarka_shared.ast_schemas` (`packages/shared-core`)
- `rule_engine.ast_schemas` is a **re-export shim** only
- `evaluator` — orchestrator `rule_shadow_test`, pack validators, e2e holy-grail (still under this package)
- Optional compose profile `legacy-python-rules` on `docker-compose.v2-ingest.yml` for dual-run / emergency rollback

Importing this package emits `DeprecationWarning`. Evaluate path of record remains decision-api.

## Parked (not on consolidated path)

| Route | Replacement |
|-------|-------------|
| `POST /v1/evaluate` | `POST {DECISION_API_URL}/v1/decisions/evaluate` |
| `POST /v1/rules/deploy`, versions, rollback | Decision-api pack GitOps / `POST /v1/admin/rules/reload` (AST promote UI returns **410**) |
| `POST /v1/hypotheses/deploy` | Redis + NATS watcher path (separate from evaluate) |

Rollback evaluate: set `RULE_EVAL_BACKEND=python` and start this service (`--profile legacy-python-rules`).
