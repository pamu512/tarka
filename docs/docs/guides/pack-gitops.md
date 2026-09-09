# Pack GitOps posture

Desk Promote is the live source of truth. Git is backup/export. A git PR is **not** required to go live.

After a successful desk Promote, Tarka appends `tarka.pack_promote_export/v1` (`schema_id`, `pack_id`, `pack_hash`, `mode`, `actor`, `reason`, `file`, `emitted_at`) to `PACK_GITOPS_EXPORT_PATH` or `rules/_loop/promote_export.jsonl`. Consumer contract: [pack-promote-export-v1](../../contracts/pack-promote-export-v1.md). Sample backup sink (commit-message stub, not go-live): [pack-promote-export-consumer](../../examples/pack-promote-export-consumer.md).

CI `policy-check` still gates pack schema. Buyer git sync consumes the export event. Write failure does not undo desk Promote. Consumer failure does not undo desk Promote.
