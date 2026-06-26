# decision-api (canonical)

Synchronous Tarka decision API — **canonical** service package.

`services/legacy_v1_decision_api/` is **deprecated** and dormant for one release cycle; see its [`DEPRECATED.md`](../legacy_v1_decision_api/DEPRECATED.md).

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
- `rules/` — symlink → `../legacy_v1_decision_api/rules` (migrate next release)
- `alembic/` — symlink → legacy migrations (migrate next release)
