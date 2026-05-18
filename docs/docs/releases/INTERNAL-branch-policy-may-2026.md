# INTERNAL — Branch policy: v1.2.0 RC freeze (through 2026-05-30)

| Field | Value |
|-------|--------|
| **Audience** | All engineers with merge rights to `pamu512/tarka` |
| **Effective** | Immediately through **`v1.2.0` tag** (target **2026-05-30**) |
| **Owner** | Release / platform (Release Manager sign-off on exceptions) |
| **Related** | [v1.2.0-rc-checklist.md](./v1.2.0-rc-checklist.md) · [v1.2.0-day60-sprint-tracker.md](./v1.2.0-day60-sprint-tracker.md) · [BRANCH_SCOPE_MAY_2026.md](./BRANCH_SCOPE_MAY_2026.md) |

---

## 1. Situation (12 days to tag)

We are shipping **`v1.2.0`** from a **single, stable Release Candidate line** on **`master`**. Epic C operational gates and Day 60 MVP work must land on that line only. Parallel work on **`1.3.0-beta`**, **local analyst UI batches**, and **[PR #170](https://github.com/pamu512/tarka/pull/170)** is real and valuable — but it is **June (v1.3.0) scope** and must not destabilize trunk before the tag.

**If `master` churns with unscoped beta/UI merges, we lose the RC SHA, re-run gates, and slip 2026-05-30.**

---

## 2. Branch map (authoritative)

```text
                    ┌─────────────────────────────────────┐
                    │  master                             │
                    │  v1.1.0 + security fixes (a287132*) │
                    │  = ONLY ancestor for v1.2.0 RC      │
                    └──────────────┬──────────────────────┘
                                   │
                          tag v1.2.0 (2026-05-30)
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  rebase / integrate (AFTER tag)     │
                    │  1.3.0-beta + PR #170 → v1.3.0    │
                    └─────────────────────────────────────┘

  1.3.0-beta ──► hypothesis pipeline, deploy-settings, HUD
  PR #170      ──► conflicting aggregate; JUNE train — do not merge to master pre-tag
  local WIP    ──► analyst UI batches — cherry-pick only if Day 60/Epic C requires

  * Refresh RC SHA at freeze; do not assume this commit in evidence bundles.
```

| Branch / artifact | Contents | May 30 role |
|-------------------|----------|-------------|
| **`master`** | `v1.1.0` baseline + security fixes; Day 60 + Epic C RC commits | **Exclusive RC branch** — tag `v1.2.0` here |
| **`1.3.0-beta`** | Hypothesis promote flow, `tarka-deploy-settings`, System Health HUD, large analyst surfaces | **Frozen out of `master`** until after tag |
| **[PR #170](https://github.com/pamu512/tarka/pull/170)** | Merge of `1.3.0-beta` (conflicting) | **June deliverable** — must **not** block or merge wholesale into RC |
| **Local analyst UI** | Uncommitted / branch-only CaseDetail, workbench, graph sidebars | **June (Q2/v1.3)** unless explicitly cherry-picked for Day 60 |

---

## 3. Policy (mandatory through tag)

### 3.1 Freeze — no wholesale merges into `master`

**PROHIBITED until `v1.2.0` is tagged:**

- Merging **`1.3.0-beta`** into `master` (in full or via **PR #170**).
- Landing **entire local analyst UI batches** on `master` “to sync progress.”
- “Quick” merge of PR #170 to fix conflicts — conflicts are expected; **resolution belongs on the June train**, not on the RC.

**ALLOWED on `master`:**

- Commits that close **Epic C RC gates**, **Day 60 MVP** ([sprint tracker](./v1.2.0-day60-sprint-tracker.md)), or **release/docs/CI** required for the tag.
- **Single-purpose** fixes (security, test, doc) with a clear v1.2.0 justification in the PR title/body.

### 3.2 Cherry-pick only — beta and local work

Any fix or Day 60 acceptance code that currently lives on **`1.3.0-beta`** or in a **local branch** must reach `master` **only** via:

1. **Identify** the minimal commit(s) (one concern per cherry-pick).
2. **Rebase or cherry-pick** onto current `master` (or an RC branch cut from `master`).
3. **Scope review** — PR description must cite the Day 60 / Epic C row it satisfies ([sprint tracker](./v1.2.0-day60-sprint-tracker.md) or [Epic C gates](../guides/counter-replay-parity.md#epic-c-release-candidate-gate-criteria)).
4. **CI green** on the RC SHA after merge — no “merge now, fix CI later” on trunk.

**Do not** open a PR titled “sync beta to master” or “merge 1.3.0-beta for v1.2.0”. That will be rejected.

### 3.3 PR #170 — June deliverable, decoupled from v1.2.0

- **[PR #170](https://github.com/pamu512/tarka/pull/170)** is designated for the **v1.3.0 / June 2026** integration window (**target 2026-06-29** per [RELEASE_SCHEDULE.md](../../../RELEASE_SCHEDULE.md)).
- It **must not** be required for Epic C sign-off, Day 60 MVP, or the **`v1.2.0`** GitHub Release.
- **Do not** use PR #170 merge status as a release gate. If CI on #170 is red, that is acceptable for May.
- After **`v1.2.0` tag**: rebase `1.3.0-beta` onto tagged `master`, resolve conflicts in a **new or updated** PR, ship as v1.3.0 work.

### 3.4 RC discipline

- Nominate one **RC SHA** on `master`; record it in [v1.2.0-rc-checklist.md](./v1.2.0-rc-checklist.md) and Epic C [evidence](./evidence/v1.2.0-epic-c/).
- **Freeze RC** 24–48h before tag except release-blocking fixes (Release Manager approval).
- Tag name: **`v1.2.0`** on the validated RC commit only.

---

## 4. Workflow (day-to-day)

| I need to… | Do this |
|------------|---------|
| Ship Epic C / Day 60 for May | Branch from **`master`** → small PR → merge to **`master`** → refresh RC SHA |
| Port a fix from beta | `git cherry-pick <sha>` (or patch) onto branch from **`master`**; separate PR; cite acceptance row |
| Continue hypothesis / HUD / workbench | Stay on **`1.3.0-beta`** or feature branch; merge to beta; **no `master`** until after tag |
| Unblock PR #170 conflicts for “May” | **Stop** — rebase #170 after v1.2.0 tag |
| Ask “can we merge beta for one file?” | Yes, **one file / one commit** via cherry-pick with sprint tracker citation |

**Suggested branch naming (optional):** `release/v1.2.0-rc` cut from `master` for final gate runs; merge back to `master` before tag. Do not cut RC from `1.3.0-beta`.

---

## 5. Exceptions

Exceptions to §3.1 require **Release Manager + one platform lead** approval in writing (PR comment or issue note) with:

- Exact commits and files.
- Which Epic C or Day 60 gate is unblocked.
- Why cherry-pick is insufficient.

Default answer for “merge all of beta”: **no**.

---

## 6. After 2026-05-30

1. Tag **`v1.2.0`** on `master`.
2. Publish GitHub Release + attach Epic C evidence.
3. Rebase **`1.3.0-beta`** onto `v1.2.0`.
4. Revive or replace **PR #170** for **v1.3.0** scope ([v1.3.0-2026-06-29.md](./v1.3.0-2026-06-29.md)).

---

## 7. Summary (post in #eng or release channel)

> **`master` only for v1.2.0 RC through May 30. No wholesale merges from `1.3.0-beta`, local analyst UI, or PR #170. Cherry-pick scoped fixes only. PR #170 is June — it does not block the tag.**

Questions: Release Manager. Scope disputes: [v1.2.0-day60-sprint-tracker.md](./v1.2.0-day60-sprint-tracker.md).
