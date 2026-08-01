# Cohort compare (case volume vs prior window)

**API:** `GET /v1/cases/analytics/cohort-compare?tenant_id=&period_days=7`  
**Proxy (UI):** `/api/cases/v1/cases/analytics/cohort-compare`

Compares cases created in the last `period_days` to the prior window of equal length.

## Response

| Field | Meaning |
|-------|---------|
| `cases_created_recent` | Count in `[now - period_days, now]` |
| `cases_created_prior` | Count in `[now - 2·period, now - period)` |
| `delta` | recent − prior |
| `delta_percent_vs_prior` | Percent change vs prior (`null` when prior is 0) |

## Permissions

- Same authentication as other case-api routes (API key or OIDC via shared auth middleware).
- **No extra role gate** on this read endpoint (same posture as `GET …/ops/kpis` and desk-activity): any authenticated client that can reach case-api may call it.
- **Production recommendation:** gate at the gateway / IdP so only **analyst+** roles reach `/api/cases/*` analytics. Mutating case routes already use `require_role("analyst")`.
- Local try-it: `ALLOW_INSECURE_NO_AUTH=true` yields an anonymous viewer principal; cohort remains readable like other read KPIs.

## UI

Cases queue (`/cases`) loads cohort compare with ops KPIs and shows recent/prior volume plus % vs prior 7d.
