# Internal-lab named pilot (G9 soak start)

Binder for the **internal-lab** named pilot. Internal lab is a valid named pilot. This page binds the [G9 soak checklist](../../docs/guides/production-install-soak-checklist.md) to an operator dry-run that dates G6 backup + G7 upgrade. It is **not** the grade.

Tarka application code is **source-available** under Elastic License 2.0 (**ELv2**, not open-source). **Beta remains.** No GA. No SOC 2 from this file. Do not invent LOI, users, or ARR. Do not name peer fraud / risk products.

## Locks

- Evaluate stays Rust. The model never ALLOW / DENY / REVIEW / Promote / demote.
- Default `enforcement.mode` is `emit_only`. Handoff is never Day-1.
- Empty plane URL = that plane off.
- Blank owner or soak date on the dry-run is **fail**.
- This binder + a green dry-run does **not** claim GitLab-grade.

## Named-pilot fields

Fill owner and soak start **before** any G9 row can count. Copy the same values onto the [soak checklist](../../docs/guides/production-install-soak-checklist.md).

| Field | Value |
|-------|-------|
| Pilot name | `internal-lab` |
| Preset / cluster | `prod-on-k8s` / other: ________ |
| Operator / owner | ________ |
| Soak start (UTC) | ________ |
| Sign-off (UTC) | ________ |
| Signer | ________ |

Unsigned / unnamed owner or date = **not** a GitLab-grade claim.

## Operator dry-run (G6 + G7 dating)

Requires `--pilot-name --owner --date`. Exits non-zero when owner or date is blank.

```bash
python3 scripts/oss/soak_backup_upgrade_dry_run.py \
  --pilot-name internal-lab \
  --owner <operator> \
  --date <UTC>
```

The script:

1. **G6** — calls [`infra/scripts/deploy/backup_restore_drill.sh --dry-run`](../../../infra/scripts/deploy/backup_restore_drill.sh). Runbook: [production-backup-restore](../../docs/guides/production-backup-restore.md).
2. **G7** — prints dated evidence and docs-links [production-upgrade](../../docs/guides/production-upgrade.md) (digest-to-digest `helm template` on the cluster host). No cluster Helm apply in CI.
3. Prints dated evidence. It does **not** sign the soak checklist.

## Related

| Doc | Role |
|-----|------|
| [production-install-soak-checklist](../../docs/guides/production-install-soak-checklist.md) | G9 named-pilot sign-off. Not the grade. |
| [production-install-v1](../../contracts/production-install-v1.md) | When a grade *may* be claimed. |
| [SUPPORT.md](../../../SUPPORT.md) | G8 commercial pack. Not this sign-off. |
| [deployment](../../docs/guides/deployment.md) | Helm catalog / `prod-on-k8s`. |

## Out of scope

- GitLab-grade claim from this binder or a green dry-run
- 1.3.0-beta publish
- Invented LOI / users / ARR
- Real cluster Helm apply in CI
