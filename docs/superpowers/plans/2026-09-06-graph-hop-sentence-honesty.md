# Graph Hop Sentence Honesty (P-graph1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two honest hop sentences — share-edge (`has_etype` only, no FLAG) and trust FLAG (shipped AND with `sibling_prior_flag`).

**Architecture:** `emitHopPack` is the single compiler. Sentence panel and visual hop node call it. Docs split Graph (identity hop) from decision-context SQLite.

**Tech Stack:** TypeScript (frontend sentences + canvas), existing `graph_v1` AST, Markdown docs.

**Spec:** [2026-09-06-graph-hop-sentence-honesty-design.md](../specs/2026-09-06-graph-hop-sentence-honesty-design.md)

**Branch:** `honesty/graph-hop-sentence-honesty` stacked on `#378` / `feat/desk-demo-vs-product`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- Empty `GRAPH_SERVICE_URL` = hops off. No new etypes / Rust atom / `desk_provision.json`.
- Signed five etypes only. No Tarka OSS / third-party desk names in new copy.

---

## File map

| File | Role |
|------|------|
| Modify: `frontend/src/utils/sentencePack.ts` | `kind: share \| trust`; two `when_ast` shapes |
| Modify: `frontend/src/utils/sentencePack.test.ts` | Share has no FLAG; trust has sibling AND |
| Modify: `frontend/src/components/SentencePackPanel.tsx` | Kind select |
| Modify: `frontend/src/components/RuleBuilder/compileHopEtype.ts` | Pass `kind` through |
| Modify: `frontend/src/components/RuleBuilder/nodes/HopEtypeNode.tsx` | Optional kind |
| Modify: `frontend/src/components/RuleBuilder/compileHopEtype.test.ts` | Both kinds match emit |
| Modify: `docs/docs/guides/hop-pack-authoring.md` | Both sentences + name split |

---

### Task 1: Emitter

**Files:** `sentencePack.ts` + test

- [ ] **Step 1:** Failing tests: share `USES_DEVICE` → `atom === "has_etype"`, tags exclude `FLAG`; trust → `when_ast` has `sibling_prior_flag` child and tags include `FLAG`.
- [ ] **Step 2:** FAIL
- [ ] **Step 3:** `HopSentence.kind` default `"share"`. Trust AST copied from `graph_v1_uses_device_v1.json` with etype swapped.
- [ ] **Step 4:** PASS
- [ ] **Step 5:** Commit `fix: hop sentences split share-edge from trust FLAG`

---

### Task 2: Desk + canvas + docs

**Files:** panel, hop node, compileHopEtype, hop-pack-authoring, architecture one-liner if needed

- [ ] **Step 1:** Canvas test: `kind: "trust"` compile equals `emitHopPack({ etype, kind: "trust" })`
- [ ] **Step 2:** FAIL if compile ignores kind
- [ ] **Step 3:** Wire panel + node `kind`; docs
- [ ] **Step 4:** `npx vitest run src/utils/sentencePack.test.ts src/components/RuleBuilder/compileHopEtype.test.ts`
- [ ] **Step 5:** Commit `fix: desk hop compiler and docs name both atoms`

---

## Test commands

```
cd frontend && npx vitest run src/utils/sentencePack.test.ts src/components/RuleBuilder/compileHopEtype.test.ts
PYTHONPATH=services/shared:services/decision-api/src python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_graph_pack_atoms.py services/decision-api/tests/test_graph_v1_uses_device_pack.py -q
```
