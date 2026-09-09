# Pack promote export v1

Event name: `tarka.pack_promote_export/v1`.

Desk Promote is the live source of truth and the go-live authority. This export is a backup of that event. Consumers must not treat this stream as Promote authority.

See [CLAIM_LOCK](../compliance/CLAIM_LOCK.md), [pack GitOps](../docs/guides/pack-gitops.md), and [SUPPORT](../../SUPPORT.md) (commercial help consuming the export — not replacing the desk).

## When emitted

After a successful desk Promote. `emit_promote_export` appends one JSONL line.

Destination: `PACK_GITOPS_EXPORT_PATH`, else `{RULES_PATH}/_loop/promote_export.jsonl` (default `rules/_loop/promote_export.jsonl`).

Write failure is debug-logged. It does not roll back Promote. A missing or late line is not a demote.

## Fields

Tip payload from `emit_promote_export`. Do not invent extra required fields.

| Field | Notes |
|-------|-------|
| `schema_id` | Always `tarka.pack_promote_export/v1` |
| `pack_id` | Promoted pack id |
| `pack_hash` | Pack hash at emit (empty string if the pack had none) |
| `mode` | Tip writes `active` on Promote |
| `actor` | Who Promoted |
| `reason` | Promote reason |
| `file` | Pack filename; may be empty |
| `emitted_at` | UTC ISO-8601 (`…Z`) |

## Ordering

Append-only JSONL. One object per line (`sort_keys=True`). Later lines are later emits. Do not rewrite history.

## Idempotency

Consumers should dedupe on `pack_id` + `pack_hash` + `emitted_at`. A copied or replayed file may repeat lines.

## Consumer responsibilities

- Treat the file as backup / audit of desk Promote, not as the live pack.
- Do not gate go-live on a git merge or PR.
- Do not treat a missing export, a delayed line, or a write failure as demote.
- Do not treat a line as Promote authority.
- Commercial assist is help consuming this export ([SUPPORT](../../SUPPORT.md)). It does not replace desk Promote.

## Out of scope (hard)

- Git merge is not the go-live gate.
- Export absence is not demote.
- This contract is not Promote authority.
- Sample consumer.
- Auto-Promote default on (stays off).
- Making CI or git merge required for Promote.
- Case CRM.
- Named incumbent compare.
