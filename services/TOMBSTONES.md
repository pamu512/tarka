# Retired / non-canonical deployables

Do not add new features here. Prefer macroservice layouts already in use:

| Path | Status | Replacement |
|------|--------|-------------|
| `services/core_v2/` | Retired for OSS golden path | `services/core-api/` |
| `services/copilot_batch/` | Retired | investigation-agent + decision intelligence layer |
| `services/legacy_v1_decision_api/` | Sync-from-`decision-api` until single tree | `services/decision-api/` (source of truth) + core-api image overlay |
| `services/rule_engine/` (Python) | Prefer Rust | `services/rule-engine/` (PyO3) |
| `services/collaboration-chat-bridge/` | Prefer embedded | `investigation-agent` `/collab` mount |
| Root `docker-compose.yml` (core_v2) | Prefer lite | `infra/deploy/docker-compose.lite.yml` |

Exact root↔`src/` mirrors under signal/graph/etc. should be deleted only after import/layout cleanup (no `sys.path` hacks).
