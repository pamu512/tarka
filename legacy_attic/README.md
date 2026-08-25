# legacy_attic

Attic, not delete. Files here were leftover at the repository root after the
v1.3 hoist. They are not on the load-bearing path. Prefer
`docs/REPOSITORY_LAYOUT.md` for the live tree.

## Moved (this PR)

| Path | Why |
|------|-----|
| `STUB_REGISTER.md` | Root pointer only. Canonical ledger is `docs/STUB_REGISTER.md`. |
| `release.sh` | Unused wrapper. Canonical entry is `scripts/release.sh`. |

## Investigated and left at repo root

These look like hoist leftovers. Grep against CI, compose, Helm, frontend,
services, and scripts showed live callers. Do not attic them without updating
those callers.

| Path | Why it stays |
|------|----------------|
| `adapters/` | `COPY` in core-api / decision-api images; vendor plugins resolve `adapters/biometrics`. |
| `knowledge/` | investigation-agent OKF roots; CI `knowledge/shared`; compose/Helm mounts. |
| `templates/` | Documented cookiecutter scaffold; ruff exclude in `pyproject.toml`. |
| `triggers/` | `triggers/immutable_cases.sql` gated by `packages/shared-core` tests. |
| `tools/` | `tools/tarka.py`, `tools/shadow` submodule, frontend Vite proxy. |
| `fuzz/` | cargo-fuzz crate; `Cargo.toml` exclude; `test_no_legacy_imports.py` prefix. |
| `rules/` | CI writes `rules/counter_parity_last.json`; example pack under `rules/examples/`. |
| `schemas/` | Repo-root `UnifiedSignalSchema`; orchestrator gate imports it. |
| `docker-compose.yml` | Advertised front door; includes `infra/deploy` lite + fraud-desk. |
| `docker-compose.local.yml` | Optional Ollama overlay; referenced by shadow_agent / docs. |
| `docker-compose.streams-ai.yml` | Wrapper to archive; named in `ARCHITECTURE.md`. |
| `cli.py` / `rules_import.py` | README + quickstart operator CLI. |
