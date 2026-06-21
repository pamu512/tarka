# Tarka v1.3.0 repository layout

Five purpose-built zones at the repository root:

```
tarka/
├── frontend/          # Single React analyst app
├── services/          # Microservices (flat Python layout for v2 core)
├── packages/          # Internal shared libraries (deploy-settings, shared-core, SDKs)
├── infra/             # Deployment manifests, CI scripts, policy gates
└── docs/              # Execution kits, runbooks, release notes
```

## services/

Primary workloads hoisted from the former `tarka_v2_core/` wrapper:

| Service | Path | Notes |
|---------|------|-------|
| Orchestrator | `services/orchestrator/main.py` | Flat layout — no `src/orchestrator/` nesting |
| Shadow agent | `services/shadow_agent/main.py` | Flat layout |
| Rule engine | `services/rule_engine/main.py` | Flat layout |
| Legacy HTTP services | `services/case-api/`, `services/graph-service/`, … | Hoisted from `legacy_attic/` |

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

## Migration

Run once after checkout (already applied on v1.3.0 branches):

```bash
python3 infra/scripts/restructure_v130_layout.py
```
