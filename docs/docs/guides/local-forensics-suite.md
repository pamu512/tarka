# Local forensic suite (Shadow add-on)

[Shadow](https://github.com/pamu512/shadow) is a **local-first forensic operations console**: React workspace, optional **Tauri 2** desktop shell, and a **FastAPI** sidecar (Polars, DuckDB, NetworkX, LangGraph agent). It is **not** part of the default Tarka Docker stack; it ships as an **optional Git submodule** under [`tools/shadow`](../../../tools/shadow) so analysts can run deep-dive workflows on a workstation without sending case CSVs to the cloud by default.

## Prerequisites

- **Node.js** (current LTS) and `npm`
- **Python 3.11+** (same baseline as Shadow’s `pyproject.toml`)
- **Rust + Cargo** — only if you want the desktop app (`npm run tauri:dev`). Otherwise use **`--web`** (browser + API).
- **Ollama** (recommended) for local LLM — see Shadow’s [README](https://github.com/pamu512/shadow/blob/master/README.md).
- **PostgreSQL** — for the recommended wiring below, start Tarka’s Postgres first (e.g. `docker compose --profile core up -d postgres` from `deploy/`).

## One-command launch (from Tarka repo root)

```bash
python tarka.py forensics
```

This will:

1. Run `git submodule update --init tools/shadow` (clone Shadow if needed).
2. Copy [`tools/shadow.tarka.env.example`](../../../tools/shadow.tarka.env.example) → `tools/shadow/.env` when `.env` is missing (points Shadow at **Tarka’s default** `fraud` database on `localhost:5432`).
3. Create `tools/shadow/.venv`, `pip install -e .`, and `npm install`.
4. Start **Tauri + Vite + API** when `cargo` is on your `PATH`; otherwise fall back to **browser + API** mode (same as `python tarka.py forensics --web`).

### Flags

| Flag | Purpose |
|------|---------|
| `--web` | Force **Vite + Uvicorn** only (no Tauri); API on `SHADOW_API_PORT` (default **8742**), UI dev server per Shadow’s `package.json`. |
| `--skip-install` | Skip `pip install` / `npm install` after the first successful setup. |
| `--init-only` | Submodule + `.env` + installs only; do not start the UI. |

## Data isolation vs sharing

- **Shared Postgres, separate tables:** Shadow’s SQLAlchemy models use names such as `cases`, `audit_logs`, etc. Tarka’s case plane uses `investigation_cases`, `case_comments`, and so on. Pointing `SHADOW_DATABASE_URL` at the same database as Tarka **does not** overwrite Tarka tables; you get one server with two apps’ schemas side by side.
- **Shadow artifacts:** DuckDB projections, uploads, and preferences live under `tools/shadow/.data/` and `tools/shadow/workspace/` (see Shadow’s docs). Keep disk encryption / OS controls as you would for any PII.

## Optional Tarka HTTP ingest

Shadow’s backend supports an **ingestion provider** that can call a Tarka ETL-style HTTP endpoint (`SHADOW_TARKA_ETL_BASE_URL`, `SHADOW_INGESTION_PROVIDER`). Configure these in `tools/shadow/.env` only when you expose a compatible ingest API; defaults keep ingestion **local** (Polars/DuckDB).

## Manual alternative (no `tarka.py`)

```bash
git submodule update --init tools/shadow
cd tools/shadow
cp ../shadow.tarka.env.example .env   # from repo root: tools/shadow.tarka.env.example
python3.11 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
npm install
npm run tauri:dev    # or: npm run dev  +  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8742
```

OpenAPI for the sidecar: `http://127.0.0.1:8742/docs` (port from `SHADOW_API_PORT`).

## See also

- [Service ports](service-ports.md) — Tarka default ports vs Shadow’s **8742** API.
- [Deployment](deployment.md) — bringing Postgres up for local wiring.
