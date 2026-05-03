# Cloud release readiness

Use this checklist before promoting Tarka cloud deployments from staging to production.

For **staged security cutover** (tenant binding, keys, Copilot/bridge headers, idempotency, rollback toggles), follow **[Production security rollout checklist](./production-security-rollout.md)** in parallel with this document.

---

## Image publication matrix

Publish immutable tags for each enabled service image:

- `tarka-decision-api`
- `tarka-case-api`
- `tarka-integration-ingress`
- `tarka-feature-service`
- `tarka-ml-scoring`
- `tarka-graph-service`
- `tarka-investigation-agent`
- `tarka-event-ingest`
- `tarka-analytics-sink`
- `tarka-graphql-gateway`
- `tarka-frontend`
- `tarka-counter-service`
- `tarka-location-service`

**Optional / external images (not in the default Helm surface):** publish tags for any **separately operated** services you connect via URL (for example a **calibration** implementation reached by **`CALIBRATION_SERVICE_URL`** on decision-api). **Collaboration chat** does **not** use a second image — it is **embedded** in `tarka-investigation-agent` (`/v1/chat/…`).

Guideline: pin deployed tags to release identifiers or commit SHAs, not `latest`.

---

## CI readiness gates

- GitHub Actions job **`cloud-preset-smoke`** runs `helm lint`, `helm template` with default chart values, `scripts/ci/cloud_preset_smoke.py`, and `helm template` with a generated `core-on-aws` values file.
- `scripts/ci/cloud_preset_smoke.py` validates that supported AWS/GCP presets generate complete values files.
- Existing compose smoke (`scripts/ci/full_stack_smoke.py`) remains the broad integration check.

---

## Observability and SLO checks

Before go-live:

- Confirm all enabled HTTP services expose and pass `/v1/health`.
- Verify metrics scrape for decision latency, error rates, queue lag, and downstream dependency failures.
- Alert on:
  - Decision API high p95/p99 latency
  - Event-ingest backlog growth
  - Analytics sink ingest failures
  - DB and cache connection exhaustion

---

## Stateful operations checklist

- Backups and restore drills are configured for Postgres, graph, and analytics stores.
- Retention policies are documented for audit and stream data.
- Managed service failover behavior is known and tested.
- Secret rotation and key rollover are rehearsed with zero-downtime expectations.

---

## Tenant and security operations

- Tenant binding is enabled where required (`TENANT_BINDING_REQUIRED`).
- API key and OIDC settings are aligned with environment access policy.
- Ingress and egress rules restrict lateral access to only required dependencies.
- Evidence-signing and audit controls are enabled for regulated workloads.
