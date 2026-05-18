# INTERNAL — Branch policy: v1.3 trunk (effective immediately)

| Field | Value |
|--------|--------|
| **Status** | **ACTIVE** — supersedes [INTERNAL-branch-policy-may-2026.md](./INTERNAL-branch-policy-may-2026.md) |
| **Trunk** | **`master`** = v1.3 development line |
| **Integration PR** | [#184](https://github.com/pamu512/tarka/pull/184) (`merge/1.3.0-beta-into-master`) |
| **Skipped** | **`v1.2.0`** — no tag, no RC freeze; [#165](https://github.com/pamu512/tarka/issues/165) closed or repurposed |

## Decision

We are **skipping v1.2.0** and moving **all development to v1.3**. The `1.3.0-beta` line (hypothesis pipeline, analyst platform UI, v2 sidecars, `legacy_attic` layout) becomes the basis for **`master`**.

## Branch map

```text
master  ──► v1.3.0 integration (PR #184)
              │
              ├── legacy_attic/   (OSS services from pre-beta layout)
              ├── tarka_v2_core/  (sidecars, orchestrator, ingest)
              ├── frontend/       (analyst workbench)
              └── tarka_v2_ui/    (decision detail, AST, etc.)

1.3.0-beta  ──► sync via PR #183, then retire or fast-forward to master
```

## Required actions

| Action | Owner |
|--------|--------|
| Merge [#183](https://github.com/pamu512/tarka/pull/183) (`master` → `1.3.0-beta`) | Release / platform |
| Merge [#184](https://github.com/pamu512/tarka/pull/184) (`1.3.0-beta` → `master`) | Release / platform |
| Close [#170](https://github.com/pamu512/tarka/pull/170) (superseded by #184) | Release |
| Close or repurpose [#165](https://github.com/pamu512/tarka/issues/165) (v1.2.0 release) | Release |
| Point new PRs at **`master`** only | All contributors |
| Stabilize CI on merged trunk (v2-sidecars + legacy paths) | Platform |

## Prohibited

- Treating **v1.2.0** Epic C / Day 60 gates as release blockers for trunk merges.
- Re-opening **v1.2.0-only** cherry-pick policy from the May memo unless explicitly needed for a hotfix on an old tag.

## Target

| Milestone | Branch | Date (planned) |
|-----------|--------|----------------|
| **v1.3.0** | `master` | 2026-06-29 ([v1.3.0-2026-06-29.md](./v1.3.0-2026-06-29.md)) |

## One-line rule

> **`master` is v1.3. Land #184, fix CI on trunk, ship `v1.3.0` — not `v1.2.0`.**
