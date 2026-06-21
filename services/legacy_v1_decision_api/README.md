# Decision API

Environment variables:

- `DATABASE_URL` — async PostgreSQL, e.g. `postgresql+asyncpg://user:pass@host:5432/fraud`
- `REDIS_URL` — e.g. `redis://localhost:6379/0`
- `FEATURE_SERVICE_URL` — optional, default empty disables
- `ML_SCORING_URL` — optional
- `GRAPH_SERVICE_URL` — optional
- `OPA_URL` — optional, e.g. `http://localhost:8181` for `/v1/data/fraud/result`
- `RULES_PATH` — path to JSON rules directory (default `./rules`)

Run: `uvicorn decision_api.main:app --host 0.0.0.0 --port 8000` from `src` on PYTHONPATH or `pip install -e .` from service dir.
