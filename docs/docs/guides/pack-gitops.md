# Pack GitOps posture

Desk Promote is the live source of truth. Git is backup/export. A git PR is **not** required to go live.

After a successful desk Promote, Tarka appends `tarka.pack_promote_export/v1` (`schema_id`, `pack_id`, `pack_hash`, `mode`, `actor`, `reason`, `file`, `emitted_at`) to `PACK_GITOPS_EXPORT_PATH` or `rules/_loop/promote_export.jsonl`. Consumer contract: [pack-promote-export-v1](../../contracts/pack-promote-export-v1.md).

CI `policy-check` still gates pack schema. Buyer git sync consumes the export event. Write failure does not undo desk Promote.
