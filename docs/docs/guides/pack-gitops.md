# Pack GitOps posture

Desk Promote is the live source of truth. Git is backup/export. A git PR is **not** required to go live.

After a successful desk Promote, Tarka appends `tarka.pack_promote_export/v1` (pack id, hash, mode, actor, reason) to `PACK_GITOPS_EXPORT_PATH` or `rules/_loop/promote_export.jsonl`.

CI `policy-check` still gates pack schema. Buyer git sync consumes the export event.
