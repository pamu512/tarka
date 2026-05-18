# Branch scope: v1.3 trunk (2026)

**Purpose:** Single development line on **`master`** after v1.2 skip.

**Enforcement:** [INTERNAL-branch-policy-v1.3.md](./INTERNAL-branch-policy-v1.3.md)

## Active target: `v1.3.0` on `master`

| In scope | Branch |
|----------|--------|
| Hypothesis promote pipeline, Trust Center, analyst workbench / CaseDetail | `master` (via [#184](https://github.com/pamu512/tarka/pull/184)) |
| v2 ingest sidecars (`tarka_v2_core/`) | `master` |
| OSS services under `legacy_attic/` | `master` |
| Q2 umbrellas [#135](https://github.com/pamu512/tarka/issues/135)–[#142](https://github.com/pamu512/tarka/issues/142) | Q2-2026 milestone |

## Skipped: `v1.2.0` (May 2026)

Epic C RC-only validation and Day 60 **v1.2.0** release criteria are **not** trunk blockers. Evidence docs remain for audit reference only.

## Integration order (current)

```text
merge/master-into-1.3.0-beta  →  1.3.0-beta   (PR #183)
merge/1.3.0-beta-into-master  →  master       (PR #184)
master  →  tag v1.3.0 (2026-06-29)
```

## Cherry-pick policy

All feature work lands on **`master`** (or short-lived branches merged to `master`). No separate beta freeze.
