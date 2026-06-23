# GitHub epic status comments — May 2026 release hygiene

**Apply before 2026-05-30:** two comment templates below (Q1 waiver batch · Q2 June roll-forward batch).

**May release train (do not link as blockers on these umbrellas):**

- [v1.2.0 RC checklist](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-rc-checklist.md)
- [Epic C evidence bundle](https://github.com/pamu512/tarka/tree/master/docs/docs/releases/evidence/v1.2.0-epic-c)
- [Day 60 MVP sprint tracker](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-day60-sprint-tracker.md)
- [INTERNAL branch policy](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/INTERNAL-branch-policy-may-2026.md)
- Release reminder [#165](https://github.com/pamu512/tarka/issues/165)

---

## Template A — paste on Q1 umbrellas [#127](https://github.com/pamu512/tarka/issues/127)–[#134](https://github.com/pamu512/tarka/issues/134)

See **Comment A** block below.

---

## Template B — paste on Q2 umbrellas [#135](https://github.com/pamu512/tarka/issues/135)–[#142](https://github.com/pamu512/tarka/issues/142) and [#55](https://github.com/pamu512/tarka/issues/55)

See **Comment B** block below.

---

## Comment A (Q1 waiver — full markdown)

```markdown
## Portfolio decision — Q1-2026 **not** on the May 30 critical path

**Status:** `Q1 umbrella — waived for May closure` · **Milestone:** remains [Q1-2026](https://github.com/pamu512/tarka/milestone/9) (overdue; re-baselined post–v1.2.0)

This umbrella will **not** be rushed to “done” before **2026-05-30**. Per the [12-month execution kit § Rebalancing rules](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/tarka-12-month-roadmap-execution-kit.md#rebalancing-rules), we are invoking the **`75/25` capacity rule** until trust/reliability gates for **[v1.2.0](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-2026-05-30.md)** are satisfied: **~75%** capacity on trust / platform / RC evidence, **~25%** on net-new product surfaces.

### May 30 priorities (link here — not this epic)

Engineering attention for the next 12 days is **only** on the **v1.2.0 Release Candidate** on `master`:

| Priority | Link |
|----------|------|
| RC checklist & tag gate | [v1.2.0-rc-checklist.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-rc-checklist.md) |
| Epic C operational evidence (**ship blocker**) | [evidence/v1.2.0-epic-c](https://github.com/pamu512/tarka/tree/master/docs/docs/releases/evidence/v1.2.0-epic-c) · [Epic C RC gates](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/counter-replay-parity.md#epic-c-release-candidate-gate-criteria) |
| Day 60 MVP (benchmarks, challenge, ingress) | [v1.2.0-day60-sprint-tracker.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-day60-sprint-tracker.md) |
| Branch freeze (no beta / PR #170 on master) | [INTERNAL-branch-policy-may-2026.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/INTERNAL-branch-policy-may-2026.md) |
| Release reminder issue | [#165 — Prepare v1.2.0](https://github.com/pamu512/tarka/issues/165) |

**Do not** treat completion of this Q1 umbrella as a prerequisite for tagging **v1.2.0**.

### This epic — disposition

| Epic | Issue | May waiver | Sub-work already on `master` (not closing umbrella) |
|------|-------|------------|-----------------------------------------------------|
| Q1-E01 | [#127](https://github.com/pamu512/tarka/issues/127) | **Non-blocking — slip** | OPA bundles under `infra/deploy/opa/`; no default-branch `policy-check` gate yet |
| Q1-E02 | [#128](https://github.com/pamu512/tarka/issues/128) | **Non-blocking — slip** | `TENANT_BINDING_REQUIRED` patterns; migration aids not shipped |
| Q1-E03 | [#129](https://github.com/pamu512/tarka/issues/129) | **Non-blocking — slip** | Deploy presets/overlays; full promotion framework open |
| Q1-E04 | [#130](https://github.com/pamu512/tarka/issues/130) | **Non-blocking — partial** | **Shipped sub-work:** `GET /v1/slo` on core services, Prometheus burn rules — [service-slos-v1.md](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/service-slos-v1.md), [v1.2.5 backlog](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/v1.2.5-execution-backlog-status.md) |
| Q1-E05 | [#131](https://github.com/pamu512/tarka/issues/131) | **Non-blocking — partial** | **Shipped sub-work:** outbound circuit breakers, `fallback_reason` on evaluate, degrade metrics — [v1.2.5 backlog](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/v1.2.5-execution-backlog-status.md) |
| Q1-E06 | [#132](https://github.com/pamu512/tarka/issues/132) | **Deferred → v1.3.0** | CI exists; automated governance sign-off checklist = June |
| Q1-E07 | [#133](https://github.com/pamu512/tarka/issues/133) | **Non-blocking — in progress** | [`packages/deploy-settings`](https://github.com/pamu512/tarka/tree/master/packages/deploy-settings) on `master`; full parity gates post-tag |
| Q1-E08 | [#134](https://github.com/pamu512/tarka/issues/134) | **Non-blocking — slip** | Scattered runbooks; Epic C weekly parity runbook added for v1.2.0 |

**Consolidated tracking:** [q1-2026-milestone-status-may-2026.md](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/q1-2026-milestone-status-may-2026.md)

### What we are **not** doing in May

- Closing Q1 umbrellas to “green the board” for [#165](https://github.com/pamu512/tarka/issues/165).
- Expanding scope (policy-as-code on every PR, full runbook pack, tenant migration program) ahead of Epic C + Day 60 RC sign-off.

### Next review

- **After `v1.2.0` tag:** restore **60/40** split; replan Q1 child issues under [Q1-2026](https://github.com/pamu512/tarka/milestone/9) or roll into Q2 with explicit owners.

---
*Automated portfolio comment — May 2026 release hygiene · Delivery / Release Management*
```

---

## Comment B (Q2 roll-forward — full markdown)

```markdown
## Portfolio decision — Q2 / Marble **In-Flight** · target **June 2026 (v1.3.0)**

**Status:** `In-Flight` · **Target train:** [v1.3.0 — 2026-06-29](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.3.0-2026-06-29.md) · **Milestone:** [Q2-2026](https://github.com/pamu512/tarka/milestone/10) (delivery window through June)

This umbrella is **actively in progress** but is **explicitly off the May 30 critical path**. Work continues on **`1.3.0-beta`** / feature branches per [INTERNAL branch policy](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/INTERNAL-branch-policy-may-2026.md). **[PR #170](https://github.com/pamu512/tarka/pull/170)** is a **June integration** item and **must not** block **v1.2.0**.

### May 30 priorities (RC evidence — link before this epic)

| Priority | Link |
|----------|------|
| RC checklist & tag gate | [v1.2.0-rc-checklist.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-rc-checklist.md) |
| Epic C operational evidence (**ship blocker**) | [evidence/v1.2.0-epic-c](https://github.com/pamu512/tarka/tree/master/docs/docs/releases/evidence/v1.2.0-epic-c) |
| Day 60 MVP scope | [v1.2.0-day60-sprint-tracker.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-day60-sprint-tracker.md) |
| Branch policy (master only until tag) | [INTERNAL-branch-policy-may-2026.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/INTERNAL-branch-policy-may-2026.md) |

### This epic — June target & May alignment

| Epic | Issue | Status | May / June notes |
|------|-------|--------|------------------|
| Q2-E01 | [#135](https://github.com/pamu512/tarka/issues/135) | **In-Flight → June** | L-sized workbench on `1.3.0-beta` / local UI; **no wholesale merge to `master` pre-tag** |
| Q2-E02 | [#136](https://github.com/pamu512/tarka/issues/136) | **In-Flight → June** | Saarthi / citation surfaces in `tarka_v2_ui`; June acceptance |
| Q2-E03 | [#137](https://github.com/pamu512/tarka/issues/137) | **In-Flight → June** | Graph explainability (snapshot graph, annotations) on beta branch |
| Q2-E04 | [#138](https://github.com/pamu512/tarka/issues/138) | **In-Flight → June** | Entity resolution utilities started; override loop completes in June |
| Q2-E05 | [#139](https://github.com/pamu512/tarka/issues/139) | **In-Flight → June** | **May:** align with **v1.2.0 benchmark harness** only (`seed: 42`, [vertical_benchmark_smoke.py](https://github.com/pamu512/tarka/blob/master/scripts/benchmarks/vertical_benchmark_smoke.py), [Day 60 tracker § Vertical packs](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/v1.2.0-day60-sprint-tracker.md)) · **June:** interactive drift/benchmark **dashboards** |
| Q2-E06 | [#140](https://github.com/pamu512/tarka/issues/140) | **In-Flight → June** | Counter catalog API exists; operator UI deferred to June |
| Q2-E07 | [#141](https://github.com/pamu512/tarka/issues/141) | **In-Flight → June** | Command palette / routes partial; finish in June |
| Q2-E08 | [#142](https://github.com/pamu512/tarka/issues/142) | **In-Flight → June** | Bridge hardened on `master`; bidirectional case actions on June train |
| Marble | [#55](https://github.com/pamu512/tarka/issues/55) | **In-Flight → June** | Meta-epic for investigation parity; tracks Q2 body of work above |

**Special case — [#139](https://github.com/pamu512/tarka/issues/139) (Drift & benchmark dashboards):**

- **In May (v1.2.0):** reproducible **simulation scorecards** and smoke thresholds — not interactive dashboards.
- **DEFERRED TO v1.3.0 (JUNE):** analyst-facing drift/benchmark dashboard UX and warehouse-backed trends.

### Integration order (after May 30)

```text
tag v1.2.0 on master → rebase 1.3.0-beta → resolve PR #170 → v1.3.0 scope
```

See [BRANCH_SCOPE_MAY_2026.md](https://github.com/pamu512/tarka/blob/master/docs/docs/releases/BRANCH_SCOPE_MAY_2026.md).

### What we expect before closing this umbrella

- Rebase onto post–`v1.2.0` `master`, child issues with acceptance criteria, and milestone sign-off on [Q2-2026](https://github.com/pamu512/tarka/milestone/10) / v1.3.0 release note — **not** before **2026-05-30**.

---
*Automated portfolio comment — May 2026 release hygiene · Delivery / Release Management*
```
