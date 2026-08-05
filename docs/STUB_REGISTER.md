# Stub Register (Tier-1 Honesty — Phase 0)

Inventory as of maturity Wave 0 close. Runtime surfaces must be **Ship**, **Delete**, or **Degrade** (501/503 + `reason_code`). Test fakes are allowed.

| Surface | Path | Disposition | Evidence |
|---------|------|-------------|---------|
| Feature store | `services/decision-api/.../feature_store_api.py` | **Ship** | Postgres metadata + ClickHouse DDL via `feature_store_engine` |
| Backtest `/run` stub | `backtest_api.py` | **Delete** | Route returns guidance to `/v1/rules/backtest/jobs` |
| Executive KPIs | `analytics_dashboards.py` | **Ship** | Real analytics engine; **503** when offline |
| SAR transport | `case-api/sar_transport_worker.py` | **Ship** | Durable jobs + SFTP worker |
| Vendor registry | `vendors/registry.py` + `bootstrap.py` | **Ship** | HTTP adapters only; no `echo_stub` |
| Visual Rego compile | rules API | **Delete/410** | Tombstone; JSON + Rust engine |
| Frontend API mocks | `frontend/src/api/client.ts` | **Degrade** | Forbidden in production builds; lean nav default |

## CI gate

```bash
python3 scripts/audit_stubs.py
python3 infra/scripts/ci/test_audit_stubs.py
```

Wired in `.github/workflows/ci.yml`.
