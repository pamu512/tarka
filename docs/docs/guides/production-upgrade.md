# Production upgrade and rollback

Helm upgrade playbook between two **beta** tags or **sha256 digests** on a single-cluster `prod-on-k8s` beachhead. Practice rollback on the named pilot before a grade claim.

Tarka application code is **source-available** under Elastic License 2.0 (**ELv2**, not open-source). **Beta remains.** This page does not claim GitLab-grade. Grade still requires G0–G8 plus the G9 checklist on a **named** last-mile / food / q-comm / gig / retail pilot — see [production-install-v1](../../contracts/production-install-v1.md). Chart catalog and `helm upgrade --install` first-apply: [deployment.md](deployment.md).

**Digests preferred for prod.** A mutable `1.3.0-beta` tag is not a pin. Tag is ignored when `coreApi.digest` / `signalApi.digest` / `investigationAgent.digest` is set.

## Locks

- Evaluate stays Rust. The model never ALLOW / DENY / REVIEW / Promote / demote.
- Default `enforcement.mode` is `emit_only`. Do not upgrade a tenant that is in `handoff` without a buyer change-control window.
- No sqlite / `emptyDir` for decisions, audit, labels, or packs.
- Single cluster. This playbook is not a multi-region failover SKU.
- No named fraud / risk product incumbents as a reference.

## Backup (G6)

Run the backup drill in [production-backup-restore.md](production-backup-restore.md) before upgrade. Record the **current** digest or Helm revision before you touch images. Keep the previous digest pullable. Redis is ephemeral (rebuild from new events).

## Preflight

1. **Record the from-pin.** Prefer the running digest over the chart tag:

   ```bash
   helm history tarka -n fraud
   helm get values tarka -n fraud --all | tee /tmp/tarka-values-before.yaml
   kubectl -n fraud get deploy -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
   ```

2. **Confirm stores.** External Postgres + Redis. In-cluster PG/Redis stay **off**. No sqlite DSN on core-api / investigation-agent.

3. **Schema.** Diff `alembic heads` against the running revision. This image may only ship **expand** revisions. Production Postgres runs `alembic upgrade head` on core-api / case-api **start** (before evaluate is ready). Helm rollback does **not** undo that. Do not ship an `upgrade()` / UP that `DROP TABLE` / `DROP COLUMN` / `TRUNCATE`s durable names (`decision_audit`, `audit_logs`, `investigation_cases`, packs, labels).

4. **Packs.** Every live file under `RULES_PATH` is pack `version` **1** (field optional; default 1). Unknown versions are **not** loaded — fail closed, logged, not silent.

5. **Enforcement.** `GET /decisions/v1/ops/enforcement-mode` returns `emit_only`. If it is `handoff`, force emit-only first (kill switches) or postpone.

6. **Template the to-pin** (same values, new digests via `--digest-map`). Empty digest is not a grade pin (`--allow-empty-digest` is CI-only).

   ```bash
   cat >/tmp/to-pin.digests.map <<'EOF'
   coreApi=sha256:<64-hex-B>
   signalApi=sha256:<64-hex-B>
   investigationAgent=sha256:<64-hex-B>
   EOF

   python3 infra/scripts/deploy/generate_cloud_values.py \
     --preset prod-on-k8s \
     --image-registry <registry>/tarka \
     --db-url "$DATABASE_URL" \
     --redis-url "$REDIS_URL" \
     --digest-map /tmp/to-pin.digests.map \
     --output /tmp/prod-on-k8s.values.yaml

   helm template tarka infra/deploy/helm/fraud-stack \
     -f /tmp/prod-on-k8s.values.yaml \
     --set global.appSecretsName=tarka-app-secrets \
     >/tmp/tarka-to.yaml
   ```

   Workload `kind` + `name` must match the from-pin render. Image lines change. `PersistentVolumeClaim` stays absent on `prod-on-k8s`.

7. **Pull the to-pin** on a node or registry mirror so rollback/upgrade cannot 404.

## Upgrade

Same release name (`tarka`), same namespace, same values file. Only the image pin moves.

```bash
helm upgrade tarka infra/deploy/helm/fraud-stack \
  -n fraud \
  -f /tmp/prod-on-k8s.values.yaml \
  --set global.appSecretsName=tarka-app-secrets
```

Wait for evaluate:

```bash
kubectl -n fraud rollout status deploy/tarka-tarka-core-api
kubectl -n fraud rollout status deploy/tarka-tarka-signal-api
kubectl -n fraud rollout status deploy/tarka-tarka-investigation-agent
```

Do not `helm uninstall`. Do not flip `postgres.enabled` or `dataPersistence.mode` in the same change.

## Verify evaluate

On Helm, decision-api is mounted at `/decisions` on core-api (`:8000`). Probes are `/decisions/v1/health` and `/decisions/v1/ready`.

```bash
# health
curl -fsS -H "X-API-Key: $API_KEY" "$CORE/decisions/v1/health"
curl -fsS -H "X-API-Key: $API_KEY" "$CORE/decisions/v1/ready"

# still advisory
curl -fsS -H "X-API-Key: $API_KEY" "$CORE/decisions/v1/ops/enforcement-mode"
# expect: "enforcement_mode": "emit_only"

# one real evaluate (idempotency + role required on production profile)
curl -fsS -X POST "$CORE/decisions/v1/decisions/evaluate" \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: upgrade-verify-$(date +%s)" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"<pilot>","event_type":"payment","entity_id":"upgrade-canary","role":"<pilot-role>","payload":{"amount":1}}'

# pack count vs preflight (field is rule_packs.active_pack_count)
curl -fsS -H "X-API-Key: $API_KEY" "$CORE/decisions/v1/ops/governance"
```

`role` is required. Empty role registry accepts a safe token (e.g. `member`); a locked registry must use a registered pilot role — unsigned / missing role is **422**, not a reason to rollback the image.

Pass: HTTP 200, pack-why / receipt present, `enforcement_mode` is `emit_only`, `rule_packs.active_pack_count` matches preflight, no 5xx burst on `/metrics`. Fail: 503 fail-closed (empty `API_KEYS`), missing idempotency, unknown pack version emptying live rules, or ready probe red — **rollback**.

## Rollback

Practiced, not theoretical. Use the revision you recorded in preflight.

```bash
helm history tarka -n fraud
helm rollback tarka <from-revision> -n fraud
kubectl -n fraud rollout status deploy/tarka-tarka-core-api
kubectl -n fraud rollout status deploy/tarka-tarka-signal-api
kubectl -n fraud rollout status deploy/tarka-tarka-investigation-agent
```

Re-run **Verify evaluate**. Buyer systems stay on their previous decisioning path until that check is green (see kill switches).

Helm rollback restores the **chart + image pin**. It does not un-apply a schema contract that already dropped a column. That is why UP never silent-destroys.

If the to-pin Deployment is stuck (`ImagePullBackOff`), rollback still works only if the from-pin digest remains in the registry.

## Schema migration policy

Expand/contract. **Never silent destroy.**

| Phase | Allowed | Forbidden |
|-------|---------|-----------|
| **Expand** (this release) | `CREATE TABLE`, `ADD COLUMN` (nullable or with default), new indexes | `DROP TABLE` / `DROP COLUMN` / `TRUNCATE` of durable names in **UP** |
| **Dual-run** | New code reads new then old; old code ignores unknown columns | Require the new column on the old binary |
| **Contract** (later release, after rollback window) | Drop unused columns/tables in a **second** UP, only after the previous digest is gone | Drop in the same release that stops writing the old shape |

The migrator production actually runs is **Alembic** (`services/decision-api/alembic/`, `services/case-api/alembic/`) via `alembic upgrade head` on pod start. Repo SQL files with `-- UP` / `-- DOWN` markers (`migrations/*.sql`) are the same policy for ops scripts. Apply **UP / `upgrade()` only**. DOWN / `downgrade()` is an explicit schema rollback, not `helm rollback`.

Durable names: `audit_logs`, `decisions`, `cases`, `tarka_outbox`, `tarka_label_dlq`, `normalized_labels`. CI: `python3 infra/scripts/ci/test_schema_migration_policy.py`.

`emptyDir` / sqlite “reset the volume” is not a migration. It is data loss. Forbidden on production-labeled presets.

## Pack compatibility

Live packs are JSON `version` **1** ([rules.md](rules.md)). Desk Promote is the live source of truth; git is export ([pack-gitops.md](pack-gitops.md)).

| Store file | Upgrade behavior |
|------------|------------------|
| `version` missing or `1`, extra unknown fields | **Load.** Older packs stay live. |
| `version` ≠ 1 | **Fail closed.** Not loaded as active/shadow. Warning log: `unsupported pack version`. Not a silent skip. |
| `mode: disabled` | Not evaluated. Visible on Observe disabled list. |
| Unreadable JSON | Warning log; file skipped. |

After upgrade, `GET /decisions/v1/ops/governance` pack count must not silently drop versus preflight. If a pack disappeared, treat it as fail-closed and rollback or restore the file — do not invent rules.

## Kill switches

Product-side: Tarka evaluate is **advisory** unless the buyer has contracted `handoff`. During upgrade, keep the buyer’s previous decisioning path (their payments / promo / courier rules) as the authority. Tarka must not be the only gate.

| Switch | How | Product-side |
|--------|-----|----------------|
| **Disable pack** | `PUT /decisions/v1/rules/{filename}/mode` body `{"mode":"disabled"}` with `X-Rule-Governance-Secret`. Or set `"mode": "disabled"` on the JSON and reload. | That pack stops scoring. Other live packs still evaluate. Not a CRM “Kill” button. Live → Observe demote is propose→confirm; disable is the incident switch. |
| **Force `emit_only`** | `TARKA_ENFORCEMENT_MODE=emit_only` on core-api (`coreApi.extraEnv` or `kubectl set env deploy/tarka-tarka-core-api`). Env is read at process start — rollout the pod. Confirm `GET /decisions/v1/ops/enforcement-mode`. | HTTP `action` is advisory. `decision.enforced` webhooks stop. Product copy must not say Tarka blocked. Contract: [enforcement-v1](../../contracts/enforcement-v1.md). |
| **Drain to previous decisioning** | 1) Force `emit_only`. 2) Disable the new/bad pack if the pin is otherwise fine. 3) `helm rollback` to the from-pin. 4) Buyer systems ignore Tarka `action` until verify is green. | Drain is **buyer-owned**. Tarka does not host the payment/promo/courier path. Empty enforcement webhook URL = that sink off. |

Dependency kill-switches (`disable_graph`, `rules_only` blend) stay in [fallback-emergency-runbook.md](fallback-emergency-runbook.md). They do not replace pack disable or helm rollback.

## Out of scope

- Multi-region active-active or region failover
- G8 SUPPORT (support window / severity matrix)
- Hosted Tarka Cloud
- Claiming GitLab-grade from a green `helm template`
- Silent block / hold / deny while `emit_only`
