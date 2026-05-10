# Chitragupta (`tarka-chitragupta`)

Lightweight **plugin registry** + **versioned capability contract** + **multi-emitter export runs** with SQLite-backed run metadata (Chitragupta-style orchestration for issues **#61–#63**).

## Run locally

```bash
cd services/chitragupta
pip install -e ".[dev]"
uvicorn chitragupta.main:app --reload --port 8012
```

## Key routes

- `GET /v1/health` — includes `server_contract_version`
- `GET|POST /v1/plugins` — discovery + registration (`PluginManifest` with `contract_version`, `capabilities`, `emitter_targets_supported`)
- `GET /v1/emitters` — `json` and `csv` targets
- `POST /v1/runs` — tenant-scoped run; `emitters` array; optional `simulate_emitter_failures` (tests) for retry visibility
- `GET /v1/runs/{run_id}` — persisted status, artifact SHA-256 map, per-emitter attempt logs

## Contract rules

- Plugin `contract_version` **major** must match `SERVER_CONTRACT` / `settings.server_contract_version` (default `1.0.0`).

## Tests

```bash
pytest tests/
```
