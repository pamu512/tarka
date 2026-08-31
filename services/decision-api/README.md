# decision-api (canonical)

Canonical evaluate service. Rust JSON packs (`tarka_rule_engine` via `tarka-core`) own allow / deny / flag / review. Python FastAPI is the HTTP layer; evaluation is Rust.

Service docs: [`docs/docs/services/decision-api.md`](../../docs/docs/services/decision-api.md). The former `legacy_v1_decision_api` tree has been removed; rules and alembic live here.

Observe: leftover promote gate + `live_rule_slip` on `GET /v1/calibration/shadow-promote-gate`. Park is tick-only. Scout-pack that would clobber a slip draft is `409 slip_draft_exists`.

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
