# Core v2

Minimal decision pipeline: **FastAPI** (`/v1/decide`), a **Rust rules bridge** (`rust_engine` via PyO3), and an **append-only PostgreSQL audit log** (`audit_logs`). No ML inference or growth/automation flows run inside this process.

## Environment variables

| Variable        | Required | Description |
|-----------------|----------|-------------|
| `DATABASE_URL`  | **Yes**  | Async SQLAlchemy URL for PostgreSQL (same DB the API writes audits to), e.g. `postgresql+asyncpg://user:password@host:5432/database` |

## Startup

Run from this directory so `main`, `db`, `ffi`, and the compiled Rust extension resolve correctly:

```bash
cd services/core_v2
export DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/yourdb'
uvicorn main:app
```

Optional bind/port (defaults are `127.0.0.1:8000`):

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Before starting, install Python dependencies, provision Postgres with the `audit_logs` schema (e.g. Alembic/migrations as you maintain elsewhere), and build/install **`rust_engine`** into the same environment (e.g. `maturin develop --release` under `rust_engine/`).

## Architecture boundary (locked)

**AI and PLG sidecars are out of scope for this API.** Any intelligent automation, recommendations, product-led growth workflows, or similar features **must** be implemented as **separate microservices** that **read from the database** (and/or other integration buses)—not inside `core_v2`. This service only validates requests, evaluates rules via Rust, persists immutable audit rows, and returns the decision string.
