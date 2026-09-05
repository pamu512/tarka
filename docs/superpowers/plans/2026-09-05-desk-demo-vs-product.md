# Desk demo vs product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demo stays a lean first-hour skin; the shipped product desk shows existing analyst jobs (visual builder, backtest, lists, simulation, analytics) without turning on the sales brochure.

**Architecture:** Add `VITE_DESK_PROFILE` (`demo` | `product` | `brochure`) in front of `leanNav`. Do not flip `VITE_LEAN_NAV=false` as the product default — that flag is brochure (`INCLUDE_DEMO_SURFACE`). Product is a third path set: demo paths plus job routes. Leftover Brief is a derived English string from labels + optional case-brief comment — no `case.receipt_brief/v1`. Sentence hops add shipped `HAS_LIST` only.

**Tech Stack:** Vite env, React lean nav, case-api leftover row, vitest, pytest.

**Spec:** [docs/superpowers/specs/2026-09-05-desk-demo-vs-product-design.md](../specs/2026-09-05-desk-demo-vs-product-design.md)

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off. No stub neighbors.
- `/cases` list stays hidden on demo and product. Leftover Hold may deep-link `/cases/:id`.
- No `case.receipt_brief/v1`. No `rate` / `baseline_ratio`. No new Rust `velocity_v1`.
- No new Day-1 `shadow_agent` overlay. LLM keys never in the SPA.
- `LEAN_NAV_PATHS` must not grow `/simulation`, `/shadow`, `/command-center`, `/investigation`, `/admin` (`scripts/audit_prod_desk_mocks.py`).
- Visual builder stays `RequireRole` RiskArchitect.
- No named third-party alert/case desks in published copy.
- Do not commit unless the user asked. Skip **Step: Commit** otherwise.

---

## File map

| File | Responsibility |
|------|----------------|
| `frontend/src/config/deskProfile.ts` | `resolveDeskProfile()`, `DeskProfile` type |
| `frontend/src/config/deskProfile.test.ts` | Profile resolution (legacy `VITE_LEAN_NAV` + new env) |
| `frontend/src/config/leanNav.ts` | Demo / product / brochure path sets + visibility |
| `frontend/src/config/leanNav.test.ts` | Product shows jobs, hides brochure; demo stays lean |
| `frontend/src/vite-env.d.ts` | `VITE_DESK_PROFILE` |
| `frontend/src/App.tsx` | `INCLUDE_DEMO_SURFACE` stays brochure-only (already imported from leanNav) |
| `frontend/Dockerfile` | Default `VITE_DESK_PROFILE=product` |
| `infra/deploy/docker-compose.fraud-desk.yml` | `VITE_DESK_PROFILE=demo` for `make demo` |
| `docs/docs/guides/clone-demo.md` | Demo vs product one paragraph |
| `services/case-api/src/case_api/leftover.py` | `leftover_brief()` |
| `services/case-api/tests/test_leftovers.py` | Brief unit |
| `frontend/src/api/client.ts` | `LeftoverRow.brief?` |
| `frontend/src/pages/Leftovers.tsx` | Brief column |
| `frontend/src/utils/sentencePack.ts` | `HAS_LIST` in `HOP_ETYPES` |
| `frontend/src/utils/sentencePack.test.ts` | HAS_LIST emit |

---

### Task 1: Desk profile resolver

**Files:**
- Create: `frontend/src/config/deskProfile.ts`
- Create: `frontend/src/config/deskProfile.test.ts`
- Modify: `frontend/src/vite-env.d.ts`

**Interfaces:**
- Consumes: `import.meta.env.VITE_DESK_PROFILE`, `import.meta.env.VITE_LEAN_NAV`
- Produces: `export type DeskProfile = "demo" | "product" | "brochure"`; `export function resolveDeskProfile(env?: { profile?: string; leanNav?: string }): DeskProfile`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { resolveDeskProfile } from "./deskProfile";

describe("resolveDeskProfile", () => {
  it("prefers VITE_DESK_PROFILE over VITE_LEAN_NAV", () => {
    expect(resolveDeskProfile({ profile: "product", leanNav: "false" })).toBe("product");
    expect(resolveDeskProfile({ profile: "demo", leanNav: "false" })).toBe("demo");
    expect(resolveDeskProfile({ profile: "brochure", leanNav: "true" })).toBe("brochure");
  });

  it("maps legacy VITE_LEAN_NAV when profile is unset", () => {
    expect(resolveDeskProfile({ leanNav: "false" })).toBe("brochure");
    expect(resolveDeskProfile({ leanNav: "true" })).toBe("demo");
    expect(resolveDeskProfile({})).toBe("demo");
  });

  it("treats unknown profile as demo", () => {
    expect(resolveDeskProfile({ profile: "enterprise" })).toBe("demo");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- --run src/config/deskProfile.test.ts`  
Expected: FAIL import `deskProfile`

- [ ] **Step 3: Write minimal implementation**

```ts
export type DeskProfile = "demo" | "product" | "brochure";

export function resolveDeskProfile(env?: { profile?: string; leanNav?: string }): DeskProfile {
  const raw = (env?.profile ?? (import.meta.env.VITE_DESK_PROFILE as string | undefined) ?? "")
    .trim()
    .toLowerCase();
  if (raw === "demo" || raw === "product" || raw === "brochure") return raw;
  const lean = (env?.leanNav ?? (import.meta.env.VITE_LEAN_NAV as string | undefined) ?? "true")
    .trim()
    .toLowerCase();
  return lean === "false" ? "brochure" : "demo";
}
```

Add to `frontend/src/vite-env.d.ts` next to `VITE_LEAN_NAV`:

```ts
readonly VITE_DESK_PROFILE?: string;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- --run src/config/deskProfile.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit** (only if the user asked)

```bash
git add frontend/src/config/deskProfile.ts frontend/src/config/deskProfile.test.ts frontend/src/vite-env.d.ts
git commit -m "feat: resolve demo/product/brochure desk profile"
```

---

### Task 2: Product path set in leanNav

**Files:**
- Modify: `frontend/src/config/leanNav.ts`
- Modify: `frontend/src/config/leanNav.test.ts`
- Modify: `frontend/src/pages/Help.tsx` (use `visibleDeskNavPaths()`)

**Interfaces:**
- Consumes: `resolveDeskProfile()` from Task 1
- Produces: `export const DESK_PROFILE: DeskProfile`; `export const PRODUCT_JOB_PATHS: Set<string>`; `LEAN_NAV === (DESK_PROFILE === "demo")`; `INCLUDE_DEMO_SURFACE === (DESK_PROFILE === "brochure")`; `isProductSurfacePath(path)`; `visibleDeskNavPaths()`

Keep `LEAN_NAV_PATHS` as the **demo** set (do not add `/simulation`).

`PRODUCT_JOB_PATHS` = every `LEAN_NAV_PATHS` entry plus:

```
/rules/visual
/ops/backtest
/entity-lists
/simulation
/analytics
```

- [ ] **Step 1: Write the failing tests** (append to `leanNav.test.ts`)

```ts
  it("product desk shows analyst jobs and hides brochure home", async () => {
    vi.stubEnv("VITE_DESK_PROFILE", "product");
    vi.stubEnv("VITE_LEAN_NAV", "true");
    vi.stubEnv("VITE_GRAPH_SERVICE_URL", "http://graph-service:8001");
    vi.resetModules();
    const {
      DESK_PROFILE,
      INCLUDE_DEMO_SURFACE,
      isNavItemVisible,
      isProductionSurfacePath,
      leanHomePath,
      LEAN_NAV_PATHS,
    } = await loadLeanNav();
    expect(DESK_PROFILE).toBe("product");
    expect(INCLUDE_DEMO_SURFACE).toBe(false);
    expect(leanHomePath()).toBe("/graph");
    expect(isNavItemVisible("/rules/visual")).toBe(true);
    expect(isNavItemVisible("/ops/backtest")).toBe(true);
    expect(isNavItemVisible("/entity-lists")).toBe(true);
    expect(isNavItemVisible("/simulation")).toBe(true);
    expect(isNavItemVisible("/analytics")).toBe(true);
    expect(isNavItemVisible("/analytics/rule-performance")).toBe(true);
    expect(isNavItemVisible("/command-center")).toBe(false);
    expect(isNavItemVisible("/exec-dashboards")).toBe(false);
    expect(isNavItemVisible("/cases")).toBe(false);
    expect(isProductionSurfacePath("/rules/visual")).toBe(true);
    expect(isProductionSurfacePath("/command-center")).toBe(false);
    expect(LEAN_NAV_PATHS.has("/simulation")).toBe(false);
  });

  it("demo desk still hides visual builder and backtest", async () => {
    vi.stubEnv("VITE_DESK_PROFILE", "demo");
    vi.resetModules();
    const { isNavItemVisible } = await loadLeanNav();
    expect(isNavItemVisible("/rules/visual")).toBe(false);
    expect(isNavItemVisible("/ops/backtest")).toBe(false);
    expect(isNavItemVisible("/simulation")).toBe(false);
    expect(isNavItemVisible("/rules")).toBe(true);
  });
```

Existing tests that stub only `VITE_LEAN_NAV` must keep passing (`true` → demo, `false` → brochure).

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd frontend && npm test -- --run src/config/leanNav.test.ts`  
Expected: FAIL `DESK_PROFILE` export / product visibility

- [ ] **Step 3: Wire leanNav.ts**

At top, after imports:

```ts
import { resolveDeskProfile, type DeskProfile } from "./deskProfile";

export const DESK_PROFILE: DeskProfile = resolveDeskProfile();
export const INCLUDE_DEMO_SURFACE = DESK_PROFILE === "brochure";
export const LEAN_NAV = DESK_PROFILE === "demo";
```

Delete the old `INCLUDE_DEMO_SURFACE` / `LEAN_NAV` assignments that read only `VITE_LEAN_NAV`.

After `LEAN_NAV_PATHS`, add:

```ts
export const PRODUCT_JOB_PATHS = new Set<string>([
  ...LEAN_NAV_PATHS,
  "/rules/visual",
  "/ops/backtest",
  "/entity-lists",
  "/simulation",
  "/analytics",
]);
```

Change `isProductionSurfacePath` to treat product extras as production when `DESK_PROFILE === "product"`:

```ts
export function isProductionSurfacePath(path: string): boolean {
  if (DESK_PROFILE === "product" && PRODUCT_JOB_PATHS.has(path)) return true;
  if (LEAN_NAV_PATHS.has(path)) return true;
  if (path === "/403-unauthorized") return true;
  if (path === "/login" || path === "/auth/callback") return true;
  if (path.startsWith("/cases/")) return true;
  if (path.startsWith("/disputes/")) return true;
  if (path === "/decisions" || path.startsWith("/decisions/")) return true;
  if (path === "/graph" || path.startsWith("/graph/")) return true;
  if (DESK_PROFILE === "product" && path.startsWith("/rules/")) return true;
  return false;
}
```

Change `isNavItemVisible` so product uses `PRODUCT_JOB_PATHS` instead of only `LEAN_NAV`:

```ts
export function isNavItemVisible(path: string): boolean {
  if (DESK_PROFILE === "demo" && !isProductionSurfacePath(path)) return false;
  if (DESK_PROFILE === "product" && !PRODUCT_JOB_PATHS.has(path) && !isProductionSurfacePath(path)) {
    return false;
  }
  if ((DESK_PROFILE === "demo" || DESK_PROFILE === "product") && path === "/cases") return false;
  if (path === "/leftovers" && !isPlaneEnabled("graph")) return false;
  if ((DESK_PROFILE === "demo" || DESK_PROFILE === "product") && path === "/graph/mule-path") return false;
  const plane = planeForPath(path);
  if (plane && !isPlaneEnabled(plane)) return false;
  return true;
}
```

Rename or add:

```ts
export function visibleDeskNavPaths(): string[] {
  const set = DESK_PROFILE === "product" ? PRODUCT_JOB_PATHS : LEAN_NAV_PATHS;
  return [...set].filter((path) => isNavItemVisible(path)).sort();
}
```

Keep `visibleLeanNavPaths` as an alias of `visibleDeskNavPaths` so Help compiles.

`leanHomePath`: brochure → `/command-center`; else graph-on → `/graph`; else `/decisions`.

- [ ] **Step 4: Run leanNav tests**

Run: `cd frontend && npm test -- --run src/config/leanNav.test.ts`  
Expected: all PASS

- [ ] **Step 5: Run mock-forbid gate**

Run: `python3 scripts/audit_prod_desk_mocks.py`  
Expected: OK (demo `LEAN_NAV_PATHS` still excludes `/simulation`)

- [ ] **Step 6: Commit** (only if asked)

```bash
git add frontend/src/config/leanNav.ts frontend/src/config/leanNav.test.ts frontend/src/pages/Help.tsx
git commit -m "feat: product desk path set without brochure home"
```

---

### Task 3: Bake product image, keep demo compose lean

**Files:**
- Modify: `frontend/Dockerfile` (ARG `VITE_DESK_PROFILE=product`; keep `VITE_LEAN_NAV=true` unused or set `demo` only when building demo)
- Modify: `infra/deploy/docker-compose.fraud-desk.yml` (`VITE_DESK_PROFILE: "demo"`)
- Modify: `docs/docs/guides/clone-demo.md` (one paragraph: demo skin vs product image)
- Modify: `frontend/src/config/leanNav.ts` file header comment (production default is **product**, not lean)

**Interfaces:**
- Consumes: Task 2 `DESK_PROFILE`
- Produces: demo compose → `demo`; Dockerfile default → `product`

- [ ] **Step 1: Fail a comment/doc grep (manual assert)**

```bash
grep -n "Production default: lean" frontend/Dockerfile frontend/src/config/leanNav.ts || true
```

Expected: those stale lines still present (you will replace them).

- [ ] **Step 2: Dockerfile args**

```dockerfile
# Shipped stack: analyst jobs (visual / backtest / lists). Not brochure.
ARG VITE_DESK_PROFILE=product
ENV VITE_DESK_PROFILE=${VITE_DESK_PROFILE}
# Legacy: true=demo, false=brochure. Ignored when VITE_DESK_PROFILE is set.
ARG VITE_LEAN_NAV=true
ENV VITE_LEAN_NAV=${VITE_LEAN_NAV}
```

- [ ] **Step 3: fraud-desk compose**

```yaml
      args:
        VITE_DESK_PROFILE: "demo"
        VITE_LEAN_NAV: "true"
```

- [ ] **Step 4: clone-demo.md after the command block**

Add:

```markdown
`make demo` is the **demo** skin (first-hour pages). The frontend image default is **product**: same APIs, plus visual builder, backtest, entity lists, simulation, and analytics. Product is not Command Center or executive brochure pages. Optional sales overlay still uses `VITE_DESK_PROFILE=brochure` / `VITE_LEAN_NAV=false`.
```

- [ ] **Step 5: Sanity**

Run: `python3 scripts/audit_prod_desk_mocks.py` and `cd frontend && npm test -- --run src/config/leanNav.test.ts src/config/deskProfile.test.ts`  
Expected: PASS

- [ ] **Step 6: Commit** (only if asked)

```bash
git add frontend/Dockerfile infra/deploy/docker-compose.fraud-desk.yml docs/docs/guides/clone-demo.md frontend/src/config/leanNav.ts
git commit -m "build: product image default; make demo stays demo skin"
```

---

### Task 4: Leftover Brief (no new schema)

**Files:**
- Modify: `services/case-api/src/case_api/leftover.py`
- Modify: `services/case-api/tests/test_leftovers.py`
- Modify: `frontend/src/api/client.ts` (`LeftoverRow.brief?`)
- Modify: `frontend/src/pages/Leftovers.tsx`
- Modify: `frontend/src/pages/Leftovers.test.tsx` if a row fixture needs `brief`

**Interfaces:**
- Consumes: `leftover_pack_id`, `leftover_rule_hits`, optional `brief_comment: str | None`
- Produces: `leftover_brief(labels, brief_comment=None) -> str`; `leftover_row` key `"brief"`

- [ ] **Step 1: Write the failing test**

```python
from case_api.leftover import leftover_brief, leftover_row

def test_leftover_brief_from_pack_hits_and_case_brief():
    assert leftover_brief(["origin:evaluate", "pack:device_signals", "hit:sdk_bot"]) == (
        "Pack device_signals — hits sdk_bot"
    )
    assert leftover_brief(["origin:evaluate"], brief_comment="# Case brief (deterministic)\n\n- x") == (
        "# Case brief (deterministic)\n\n- x"
    )
    assert leftover_brief(["origin:evaluate"], brief_comment="System: case brief unreachable") == ""
    row = leftover_row(
        _case(id="c1", labels=["origin:evaluate", "pack:device_signals", "hit:sdk_bot"]),
        sla_breached=False,
        brief_comment=None,
    )
    assert row["brief"] == "Pack device_signals — hits sdk_bot"
    assert "receipt_brief" not in row
```

- [ ] **Step 2: Run to verify fail**

Run: `cd services/case-api && PYTHONPATH=src:.:../shared python3 -m pytest tests/test_leftovers.py::test_leftover_brief_from_pack_hits_and_case_brief -q`  
Expected: FAIL import `leftover_brief`

- [ ] **Step 3: Implement**

```python
def leftover_brief(labels: list[str] | None, brief_comment: str | None = None) -> str:
    comment = str(brief_comment or "").strip()
    if comment.startswith("System:"):
        comment = ""
    pack = leftover_pack_id(labels)
    hits = leftover_rule_hits(labels)
    bits: list[str] = []
    if pack:
        bits.append(f"Pack {pack}")
    if hits:
        bits.append("hits " + ", ".join(hits))
    base = " — ".join(bits)
    if comment and not base:
        return comment[:500]
    if comment and base:
        return f"{base} — {comment[:240]}"
    return base
```

`leftover_row(..., brief_comment: str | None = None)` sets `"brief": leftover_brief(labs, brief_comment)`.

List handler: if comments are already loaded on the case, pass the newest non-empty `CaseComment.body`. If the list query does not join comments, pass `None` (pack/hits brief is enough). Do **not** add a new HTTP resource or schema id.

- [ ] **Step 4: Desk column**

In `Leftovers.tsx` add a **Brief** column (`data-testid="leftover-brief"`) showing `row.brief || "—"`. Keep fail-close. Do not mention a receipt_brief contract.

`LeftoverRow` in `client.ts`: `brief?: string`.

- [ ] **Step 5: Run tests**

```bash
cd services/case-api && PYTHONPATH=src:.:../shared python3 -m pytest tests/test_leftovers.py::test_leftover_brief_from_pack_hits_and_case_brief tests/test_leftovers.py::test_leftover_row_reads_pack_and_hits_from_labels -q
cd frontend && npm test -- --run src/pages/Leftovers.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit** (only if asked)

```bash
git add services/case-api/src/case_api/leftover.py services/case-api/tests/test_leftovers.py frontend/src/api/client.ts frontend/src/pages/Leftovers.tsx frontend/src/pages/Leftovers.test.tsx
git commit -m "feat: leftover Brief from pack hits and case-brief comment"
```

---

### Task 5: Sentence hop `HAS_LIST`

**Files:**
- Modify: `frontend/src/utils/sentencePack.ts`
- Modify: `frontend/src/utils/sentencePack.test.ts`

**Interfaces:**
- Consumes: existing `emitHopPack`
- Produces: `HOP_ETYPES` includes `"HAS_LIST"`

- [ ] **Step 1: Write the failing assertion**

```ts
  it("emits HAS_LIST from the shipped etype list", () => {
    const pack = emitHopPack({ etype: "HAS_LIST" });
    const rule = (pack.rules as Array<{ when_ast: { etype: string } }>)[0];
    expect(rule.when_ast.etype).toBe("HAS_LIST");
    expect(pack.mode).toBe("shadow");
  });
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npm test -- --run src/utils/sentencePack.test.ts`  
Expected: FAIL type / etype fallback to `USES_DEVICE`

- [ ] **Step 3: One-line catalog change**

```ts
export const HOP_ETYPES = ["USES_DEVICE", "HAS_EMAIL", "HAS_PHONE", "HAS_CARD", "HAS_LIST"] as const;
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npm test -- --run src/utils/sentencePack.test.ts`  
Expected: PASS

- [ ] **Step 5: Commit** (only if asked)

```bash
git add frontend/src/utils/sentencePack.ts frontend/src/utils/sentencePack.test.ts
git commit -m "feat: sentence hop dropdown includes HAS_LIST"
```

---

### Task 6: Regression sweep

**Files:** none new

- [ ] **Step 1: Frontend desk + leftovers + sentences**

```bash
cd frontend && npm test -- --run src/config/deskProfile.test.ts src/config/leanNav.test.ts src/utils/sentencePack.test.ts src/pages/Leftovers.test.tsx src/components/FirstHourHint.test.ts
```

Expected: all PASS

- [ ] **Step 2: Leftover + walk + policy**

```bash
cd services/case-api && PYTHONPATH=src:.:../shared python3 -m pytest tests/test_leftovers.py::test_leftover_brief_from_pack_hits_and_case_brief tests/test_leftovers.py::test_leftover_row_reads_pack_and_hits_from_labels -q
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py
python3 scripts/audit_prod_desk_mocks.py
python3 infra/scripts/policy/validate_rule_packs.py
```

Expected: PASS / OK

- [ ] **Step 3: Confirm no receipt_brief**

```bash
rg -n "receipt_brief" services/case-api frontend/src || true
```

Expected: no matches in those trees

---

## Spec coverage

| Spec requirement | Task |
|------------------|------|
| Three profiles, do not flip `LEAN_NAV=false` as product | 1, 2, 3 |
| Demo = today’s lean; product adds visual/backtest/lists/simulation/analytics | 2 |
| Brochure unchanged (`INCLUDE_DEMO_SURFACE`) | 2 |
| Dockerfile product / compose demo | 3 |
| Leftover Brief = pack-why labels + case-brief, no new schema | 4 |
| `HAS_LIST` sentence hop | 5 |
| Planes still empty-URL off; `/cases` hidden | 2 |
| Tests listed in spec | 6 |
