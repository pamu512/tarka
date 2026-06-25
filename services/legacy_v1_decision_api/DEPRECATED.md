# DEPRECATED — `legacy_v1_decision_api`

**Status:** Dormant for one release cycle. **Do not extend.**  
**Canonical package:** [`services/decision-api`](../decision-api/)

## What moved

| Was (legacy) | Now (canonical) |
|---|---|
| `legacy_v1_decision_api/src/decision_api/` | `decision-api/src/decision_api/` |
| Docker / compose builds | `services/decision-api/Dockerfile` |
| Policy validation (`infra/scripts/policy/`) | `services/decision-api` + `decision-api/rules/` |
| `core-api` decision module COPY | `services/decision-api/src/decision_api` |

## Still borrowed from this tree (temporary)

Until the next release, canonical builds may **symlink or COPY** from here:

- `rules/` — JSON rule packs
- `alembic/` + `alembic.ini` — Postgres migrations
- `static/` — bundled static assets

## Runtime

If this package's `main.py` is started directly, it logs a **DEPRECATION** warning at startup.

## Removal target

Delete `services/legacy_v1_decision_api/` after one release cycle once:

1. Rule packs and migrations live under `services/decision-api/`
2. CI tests run from `services/decision-api/tests/` against canonical `src/`
3. No Dockerfile or compose file references this path
