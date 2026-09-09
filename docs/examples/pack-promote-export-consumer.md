# EXAMPLE: pack promote export consumer (backup sink)

Desk **Promote** is the live source of truth. This sample reads `tarka.pack_promote_export/v1` JSONL after Promote and writes a commit-message stub. Git is backup. A stub is **not** go-live authority.

```
# after desk Promote, emit_promote_export appends one JSONL line
python scripts/pack_promote_export_consumer.py \
  --input rules/_loop/promote_export.jsonl \
  --out-dir backup/promote-stubs
# replay is safe: same pack_id + pack_hash + emitted_at → same file, no rewrite
```

Idempotency key: `pack_id` + `pack_hash` + `emitted_at` (same as [pack-promote-export-v1](../contracts/pack-promote-export-v1.md)).

Empty `PACK_PROMOTE_EXPORT_CONSUMER_URL` (and empty `--notify-url`) = outbound notify off. Consumer failure does not roll back Promote and does not demote.

See [pack GitOps](../docs/guides/pack-gitops.md). Commercial help consuming the export: [SUPPORT — Pack GitOps export assist](../../SUPPORT.md#pack-gitops-export-assist).
