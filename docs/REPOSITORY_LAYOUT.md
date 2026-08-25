# Tarka v1.3.0 repository layout

Five purpose-built product zones:

```
tarka/
├── frontend/          # Single React analyst app
├── services/          # Microservices (flat Python layout for v2 core)
├── packages/          # Internal shared libraries (deploy-settings, shared-core, SDKs)
├── infra/             # Deployment manifests, CI scripts, policy gates
└── docs/              # Execution kits, runbooks, release notes
```

The repository root also has other **load-bearing** trees (not leftover):
`crates/`, `tests/`, `scripts/`, `sdk/`, `proto/`, `contracts/`, `migrations/`,
`adapters/`, `knowledge/`, `tools/`, `rules/`, `schemas/`, `triggers/`,
`templates/`, `fuzz/`. Compose front doors (`docker-compose.yml` and overlays)
stay at root and include files under `infra/deploy/`.

Leftover root pointers live in [`legacy_attic/`](../legacy_attic/README.md)
(attic, not delete).

## services/

Primary workloads hoisted from the former `tarka_v2_core/` wrapper:

| Service | Path | Notes |
|---------|------|-------|
| decision-api | `services/decision-api/src/decision_api/` | Canonical evaluate (Rust packs via `tarka-core`) |
| core-api | `services/core-api/src/core_api/` | Macroservice mounting `/decisions` + `/cases` |
| Orchestrator | `services/orchestrator/main.py` | Ingest rail; flat layout |
| Shadow agent | `services/shadow_agent/main.py` | LLM advise (optional); flat layout |
| Rule engine | `services/rule_engine/main.py` | **Legacy** dual-run / rollback only (`RULE_EVAL_BACKEND=python`) |
| case-api | `services/case-api/` | Residual cases from evaluate deny/review |
| graph-service | `services/graph-service/` | Entity graph + decision-accountability SoR (optional; `--profile graph`) |
| investigation-agent | `services/investigation-agent/` | Pack-why on residual cases; copilot (advise only) |

## packages/

| Package | Path |
|---------|------|
| Deploy settings schema | `packages/deploy-settings/` |
| Shared DB/audit models | `packages/shared-core/tarka_shared/` |
| SDKs | `packages/fraud-sdk-*` |

## infra/

| Area | Path |
|------|------|
| Docker Compose + Helm + OPA | `infra/deploy/` |
| CI / deploy / policy scripts | `infra/scripts/{ci,deploy,policy}/` |

## docs/

| Path | Role |
|------|------|
| [`INDEX.md`](INDEX.md) | Operator hub |
| [`docs/`](docs/) + [`mkdocs.yml`](mkdocs.yml) | MkDocs site source (`mkdocs serve` from `docs/`; do not commit `site/`) |
| [`guides/`](docs/guides/) via `docs/docs/guides/` | Runbooks (flows, deploy, honesty) |
| [`superpowers/`](superpowers/) | Recent design specs/plans only |
| [`compliance/`](compliance/) | Control narratives (not certifications) |
| Wiki mirror | [`wiki/`](wiki/) — publish with [`scripts/docs/sync-github-wiki.sh`](../scripts/docs/sync-github-wiki.sh); hub wins on conflict |

Root product docs: [`../README.md`](../README.md), [`../VISION.md`](../VISION.md), [`../ARCHITECTURE.md`](../ARCHITECTURE.md), [`STUB_REGISTER.md`](STUB_REGISTER.md).

## Migration

Run once after checkout (already applied on v1.3.0 branches):

```bash
python3 infra/scripts/restructure_v130_layout.py
```
