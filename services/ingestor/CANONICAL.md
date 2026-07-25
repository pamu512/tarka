# Canonical layout for services/ingestor

**Canonical package path:** `src/ingestor/` (import as `ingestor.*`).

**Do not delete the flat root `.py` modules yet.** Both layouts are still live:

| Path | Role |
|------|------|
| `src/ingestor/` | Package imports (`from ingestor.manifest_schema import …`). Preferred. Includes `schemas.py` and the fuller `manifest_schema` (e.g. `TransactionSchema`). |
| Root `*.py` (flat) | Still on some `PYTHONPATH` entries (`../ingestor` in orchestrator/shadow_agent) and copied wholesale into Docker images. Several files match `src/`; `manifest_schema.py` does **not** (src is ahead). |

**Callers today**

- Package style: orchestrator, shadow_agent, e2e/integration tests (`from ingestor…` with `services/ingestor/src` on `PYTHONPATH`).
- Flat path still listed beside src in `services/orchestrator/pyproject.toml` (`pythonpath` includes both `../ingestor` and `../ingestor/src`).

**Follow-up**

1. Point all Docker/`PYTHONPATH` entries at `src` only.
2. Diff/reconcile flat vs `src` (especially `manifest_schema.py`).
3. Delete flat root modules and set `[tool.setuptools.packages.find] where = ["src"]`.
