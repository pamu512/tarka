# Production backup / restore (decisions + audit)

Operator drill for the **buyer SoR** on external Postgres. This is not a Tarka-operated backup product and not a GitLab-grade claim by itself.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). Production requires **external Postgres**. In-cluster PG / sqlite / `emptyDir` are not a production restore target.

**Out of scope:** hosted backup SaaS, Tarka Cloud backup, [upgrade](./deployment.md) docs (G7).

## What is source of truth

Buyer `DATABASE_URL` (Helm `global.externalServices.postgres.databaseUrl`) holds evaluate + desk state for `prod-on-k8s` / `enterprise-desk-on-k8s`. Dump the tables that exist. Skip names that are absent on an evaluate-only install.

| Family | Tables (if present) | Why |
|--------|---------------------|-----|
| **Decisions + audit** | `decision_audit`, `vendor_integration_audit`, `inference_logs` | Every evaluate receipt. Replay and dispute start here. |
| **Packs** | `rule_approvals`, `backtest_runs`, `fraud_rules`, `engine_rules` | Live / approved pack identity and maker–checker tokens. |
| **Labels** | `investigation_label_drafts`, `leftover_promote_acks`, `normalized_labels` | Analyst `y_label`, leftover promote acks, ground truth. |
| **Leftover claim** | `investigation_cases` (`claimed_by` / `claimed_at` / leftover rows) | Claim is columns on cases, not a second SoR. |

`RULES_PATH` JSON on disk is a pack **input**. After Promote, durable identity is the Postgres rows above plus the optional GitOps export (below). Restoring only the image tag does not restore packs.

## Redis is ephemeral

Redis holds **velocity** (`fraud:agg:…` / `fraud:aggval:…`) and OIDC desk state. It is **not** the SoR.

- After a Postgres restore, counters **rebuild from new events**. History in Redis is gone.
- Optional: replay aggregates from `decision_audit` ([redis-agg-key-version-migration](./redis-agg-key-version-migration.md) § C, [counter-replay-parity](./counter-replay-parity.md)).
- Do not treat a Redis RDB/AOF as an RPO target. Do not fail a restore drill because Redis is empty.

## Object export (if present)

Include these **only when the operator turned them on**. Missing path = that plane off — do not invent a bucket.

| Artifact | Env / default | Restore |
|----------|---------------|---------|
| Immutable decision JSONL | `DECISION_LOG_PATH` (`./data/decision_logs/decision-log.jsonl`) | Copy the file (or warehouse export). Hash chain is append-only. |
| Pack GitOps export | `PACK_GITOPS_EXPORT_PATH` or `rules/_loop/promote_export.jsonl` | Copy the JSONL. Git is backup of Promote events, not the live pack. |
| Warehouse dual-write | `DECISION_LOG_WAREHOUSE_URL` | Buyer warehouse job; Tarka does not host it. |

See [immutable-decision-records](./immutable-decision-records.md) and [pack-gitops](./pack-gitops.md).

## Tenant policy examples (not SLAs)

Tarka does not publish an RPO/RTO. Write numbers in **your** tenant policy. These are examples for a last-mile / food / q-comm / gig / retail beachhead — not commitments.

| Example policy | RPO (example) | RTO (example) | How you get it |
|----------------|---------------|---------------|----------------|
| Hourly logical dump + 15 min WAL on buyer RDS | 15 minutes | 60 minutes | Managed PITR + this drill rehearsed on a scratch DB |
| Nightly dump only | 24 hours | 4 hours | `pg_dump` of SoR tables + object-export copy |

Redis empty after restore is expected. Do not set Redis RPO in the same policy as Postgres.

## AGE Hunt (`enterprise-desk`)

`enterprise-desk-on-k8s` is **split-plane**: buyer SoR Postgres for decisions/audit/packs/labels; Tarka `age-postgres` sidecar for Hunt hops. Do **not** point `DATABASE_URL` at `age-postgres`.

Apache AGE encodes catalog OIDs into graphids. **Logical `pg_dump` / `pg_restore` of the Hunt DB breaks hops** (`graph with oid N does not exist`). Restore Hunt the same class as `pg_basebackup`: filesystem / volume snapshot.

Shipped drill: [`scripts/oss/age_restore_drill.sh`](../../../scripts/oss/age_restore_drill.sh) (Person→Device hop after volume restore). CI contract: `infra/scripts/ci/test_age_restore_drill.py`.

Do not mix AGE data into the SoR dump. Restore SoR first, then Hunt volume, then prove a hop.

## Drill

```bash
# CI / laptop — no destroy. Prints inventory + checks tools.
bash infra/scripts/deploy/backup_restore_drill.sh --dry-run

# Isolated Postgres in Docker (safe). Proves dump → restore → row identity.
bash infra/scripts/deploy/backup_restore_drill.sh --docker-smoke

# Operator scratch restore. Source is never dropped. Target must be a *different* database.
TARKA_BACKUP_RESTORE_CONFIRM=I_UNDERSTAND \
  DATABASE_URL='postgresql://user:pw@rds:5432/fraud' \
  TARKA_BACKUP_RESTORE_URL='postgresql://user:pw@rds:5432/fraud_restore_scratch' \
  bash infra/scripts/deploy/backup_restore_drill.sh --live
```

### Prerequisites (`--live`)

- External Postgres you own. `prod-on-k8s` / `enterprise-desk` already require this.
- `pg_dump`, `pg_restore`, `psql` on PATH **or** Docker (the script can exec client tools from `postgres:16`).
- `TARKA_BACKUP_RESTORE_URL` is a **scratch** database (different name or host). The script refuses when source and target normalize to the same URL.
- Confirm env `TARKA_BACKUP_RESTORE_CONFIRM=I_UNDERSTAND`.
- Object-export paths optional: set `DECISION_LOG_PATH` / `PACK_GITOPS_EXPORT_PATH` if you want those files copied into the backup dir.

`--dry-run` is the CI default. Live restore onto the production database is not offered.

## Pass / fail

| Pass | Fail |
|------|------|
| SoR tables that existed on source exist on scratch with matching row counts for the dumped set | Restore onto the source URL; sqlite / in-cluster PG treated as production |
| Redis empty after restore, documented | Treating Redis dump as SoR; failing the drill because velocity keys are missing |
| Hunt (if enterprise-desk) restored via volume; hop query works | `pg_dump` of `age-postgres` as the Hunt backup |
| Object exports copied only when paths exist | Inventing a Tarka backup bucket |

## Related

- [Deployment](./deployment.md) — external PG/Redis, `prod-on-k8s`
- [SRE Compose profiles](../operations/sre-compose-profiles.md) — Lite AGE on the same laptop PG is **not** this drill
- Governance checklist item `stateful-backup-restore` — this guide + the script are the rehearsal
