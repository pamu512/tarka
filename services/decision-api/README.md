# decision-api (canonical)

Synchronous Tarka decision API — **canonical** service package.

Canonical decision service. The former `legacy_v1_decision_api` tree has been removed; rules and alembic live here.

## Build & run

```bash
docker build -f services/decision-api/Dockerfile -t tarka/decision-api:local .
```

```bash
cd services/decision-api
pip install -e ".[dev]"
PYTHONPATH=src:../shared RULES_PATH=rules uvicorn decision_api.main:app --port 8000
```

## Layout

- `src/decision_api/` — application code
- `docs/decision-api-graph-service-contract.md` — evaluate ↔ graph-service contract
- `rules/` — JSON rule packs (owned by this package)
- `alembic/` — migrations (owned by this package; no longer a symlink to legacy_v1)
