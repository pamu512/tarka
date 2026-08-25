# legacy_attic

Attic, not delete. Files here were leftover at the repository root after the
v1.3 hoist. They are not on the evaluate/desk path. Prefer
`docs/REPOSITORY_LAYOUT.md` for the live tree.

Do not re-run `infra/scripts/restructure_v130_layout.py`. That one-shot hoist
script still `rmtree`s `legacy_attic/` after rewriting paths.

## Moved (this PR)

| Path | Why |
|------|-----|
| `STUB_REGISTER.md` | Root pointer only. Canonical ledger is `docs/STUB_REGISTER.md`. |
| `release.sh` | Unused wrapper. Canonical entry is `scripts/release.sh`. |
| `templates/` | Cookiecutter scaffold only. Guide + ruff exclude updated. |
| `fuzz/` | cargo-fuzz crate. `Cargo.toml` exclude + legacy-import prefix updated. |
| `triggers/` | `immutable_cases.sql`. shared-core gate path updated. |

## Investigated and left at repo root

Evaluate/desk risk — do not attic before the buyer demo.

| Path | Why it stays |
|------|----------------|
| `adapters/` | `COPY` in core-api / decision-api images; vendor plugins resolve `adapters/biometrics`. |
| `knowledge/` | investigation-agent OKF roots; CI `knowledge/shared`; compose/Helm mounts. |
| `tools/` | `tools/tarka.py`, `tools/shadow` submodule, frontend Vite proxy. |
| `rules/` | CI writes `rules/counter_parity_last.json`; example pack under `rules/examples/`. |
| `schemas/` | Repo-root `UnifiedSignalSchema`; orchestrator gate imports it. |
| `docker-compose.yml` | Advertised front door; includes `infra/deploy` lite + fraud-desk. |
| `docker-compose.local.yml` | Optional Ollama overlay; referenced by shadow_agent / docs. |
| `docker-compose.streams-ai.yml` | Wrapper to archive; named in `ARCHITECTURE.md`. |
| `cli.py` / `rules_import.py` | README + quickstart operator CLI. |
