# Branch scope: May 2026 (v1.2.0) vs June 2026 (v1.3.0)

**Purpose:** Prevent May release scope creep from `1.3.0-beta` / PR #170 and local analyst UI work.

**Enforcement (team policy):** [INTERNAL-branch-policy-may-2026.md](./INTERNAL-branch-policy-may-2026.md) — urgent memo through **2026-05-30** tag.

## May 30 target: `v1.2.0` on `master` (RC)

| In scope | Branch |
|----------|--------|
| Epic C RC gates | `master` + evidence under [evidence/v1.2.0-epic-c](./evidence/v1.2.0-epic-c/) |
| Day 60: vertical benchmark seed, challenge escalation metadata, ingress scorecards SLA/remediation | `master` |
| Security / CI green on RC | `master` |

**Do not** block v1.2.0 on merging all of PR #170.

## June 29 target: `v1.3.0`

| In scope | Branch |
|----------|--------|
| Hypothesis promote pipeline, Trust Center, large CaseDetail / workbench | `1.3.0-beta` → rebase onto `master` **after** `v1.2.0` tag |
| Q2 umbrellas [#135](https://github.com/pamu512/tarka/issues/135)–[#142](https://github.com/pamu512/tarka/issues/142) | Track on Q2-2026 milestone |

## Cherry-pick policy

From `1.3.0-beta` or local frontend diff → `master` **only** when:

1. Required for v1.2.0 acceptance (Epic C, Day 60 table in [v1.2.0-2026-05-30.md](./v1.2.0-2026-05-30.md)), and  
2. Reviewed as isolated commit(s), not wholesale merge.

## Integration order

```text
master (v1.2.0 RC) → tag v1.2.0 → rebase 1.3.0-beta → PR to master for v1.3.0
```
