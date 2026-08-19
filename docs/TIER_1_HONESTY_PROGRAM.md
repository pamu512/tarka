# Tier-1 Honesty Program

Eliminate Potemkin surfaces: **ship durable execution**, **delete** the route, or **degrade** with an explicit contract (501/503 + reason). Never invent success.

## Checklist (closed tracks)

- Feature store → Postgres metadata + ClickHouse DDL (no `_STORE` SoR)
- Backtest → jobs path only; stub `/run` removed
- Executive KPIs → real analytics or **503**
- SAR transport → durable filing + worker
- Vendors → HTTP adapters via `vendors/bootstrap.py`
- Visual rules → native Rust `tarka_rule_engine` (no Rego transpile)
- CI: `scripts/audit_stubs.py`, `scripts/audit_prod_desk_mocks.py`
- Desk-strict + invent-success fail-closed (see [`STUB_REGISTER.md`](STUB_REGISTER.md))

## Policy

1. No in-process dicts as authoritative state.
2. No `status: stub` as HTTP 200 success.
3. Timeouts, retries, idempotency on real connections.
4. Rip-out allowed until a surface can be honest.

## Related

- [`STUB_REGISTER.md`](STUB_REGISTER.md) — living ledger  
- [`docs/docs/honesty.md`](docs/honesty.md) — MkDocs pointer  
- [`compliance/CLAIM_LOCK.md`](compliance/CLAIM_LOCK.md) — marketing claim hygiene  
- [`docs/docs/guides/repo-productionization-runbook.md`](docs/guides/repo-productionization-runbook.md)
