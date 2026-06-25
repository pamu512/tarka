# Cloud release readiness

Use this checklist before promoting Tarka cloud deployments from staging to production.

**Automated governance sign-off:** CI validates [`infra/deploy/release/governance-checklist.yaml`](../../../infra/deploy/release/governance-checklist.yaml) on every PR via `scripts/release/validate_governance_checklist.py`. Each item has a named owner in `owners_registry`; complete all `ci_required: true` items before production promotion.

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

- GitHub Actions job **`cloud-preset-smoke`** runs `helm lint`, `helm template` with default chart values, `infra/scripts/ci/cloud_preset_smoke.py`, and `helm template` with a generated `core-on-aws` values file.
- **`lint`** job runs **`scripts/release/validate_governance_checklist.py`** against [`infra/deploy/release/governance-checklist.yaml`](../../../infra/deploy/release/governance-checklist.yaml) (Q1-E06 release sign-off automation).
- `infra/scripts/ci/cloud_preset_smoke.py` validates that supported AWS/GCP presets generate complete values files.
- Existing compose smoke (`infra/scripts/ci/full_stack_smoke.py`) remains the broad integration check.

### Policy-as-code gate (Q1-E01)

Default-branch PRs must pass these **lint** job steps (see `.github/workflows/ci.yml`):

| Gate | Script | Scope |
| --- | --- | --- |
| Legacy rule packs (v1) | `infra/scripts/policy/validate_rule_packs.py` | `services/decision-api/rules/*.json` (symlink to legacy until migrated) |
| Hetu rule-engine AST packs (v2) | same script | `services/rule_engine/rule_packs/` (+ test fixtures) |
| OPA bundle | `infra/scripts/policy/validate_opa_bundle.py` | `infra/deploy/opa/*.rego` (`opa check --strict` + eval smoke) |
| Default deployment profile drift | `infra/scripts/policy/validate_deployment_profile_manifest.py` | `infra/deploy/profiles/default-deployment-profile.yaml` vs Helm `values.yaml` + `docker-compose.production-hardening.yml` |
| Typology DSL pins | `infra/scripts/policy/validate_typology_dsl.py` | typology + predicate registry |

**Manifest:** `infra/deploy/profiles/default-deployment-profile.yaml` is the versioned contract for production-default security posture. Update the manifest and referenced surfaces together when changing default tenant-binding or auth flags.

**Local pre-flight:**

```bash
python infra/scripts/policy/validate_rule_packs.py
python infra/scripts/policy/validate_opa_bundle.py
pip install pyyaml && python infra/scripts/policy/validate_deployment_profile_manifest.py
```

### Tenant binding regression (Q1-E02)

- Job **`test-shared-auth`** matrix: `TENANT_BINDING_REQUIRED=true|false`.
- Covers `services/shared/tests/test_auth.py` and `scripts/security/tenant_binding_smoke.py`.

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
