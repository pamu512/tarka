# Desk skins: demo vs product (A residual + C jobs)

**Date:** 2026-09-05  
**Status:** Design — not implemented.  
**Related:** [ease-of-use prompts](../plans/2026-09-05-ease-of-use-prompts.md), [leftover Hunt production](./2026-08-31-leftover-hunt-production-design.md), `frontend/src/config/leanNav.ts`

## Goal

Two skins, one stack:

| Skin | Who | Bar |
|------|-----|-----|
| **Demo** | Clone-and-run (`make doctor && make demo`) | Lean first-hour: one job per page, one printed click |
| **Product** | End-user operator desk | Full **analyst jobs** that already exist in the tree |

Demo may be lean. The shipped product image **must not** be lean.

This is **not** persona workspaces (role-first UX). That is a later slice.

## Why not flip `VITE_LEAN_NAV`

Today:

- `VITE_LEAN_NAV=true` (Dockerfile + `docker-compose.fraud-desk.yml`) = thin desk.
- `VITE_LEAN_NAV=false` = `INCLUDE_DEMO_SURFACE` = Command Center, exec KPIs, promo/seller pitch, mule-path, OSINT brochure.

Flipping the default to `false` unhides **sales home**, not “analyst jobs.” The boolean is inverted vs the product split. Do not treat `false` as the product skin.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off (`graph` / `advise` / `signals`). No stub neighbors.
- Leftovers stay the queue. Do not unhide fat `/cases` as home or nav on demo **or** product.
- No `case.receipt_brief/v1`. Brief = existing pack-why + existing case-brief comment.
- No `rate` / `baseline_ratio` runtime. No new Rust `velocity_v1` atom.
- No new `shadow_agent` compose overlay on Day-1. BYO stays `.env` + existing scout-pack.
- No named third-party alert/case desks in published copy.
- Visual builder stays `RequireRole` RiskArchitect (nav visible on product; 403 if role missing).
- License Elastic-2.0. Keep `scripts/oss/` path names.

## Three profiles

Replace the two-state lean/brochure split with an explicit profile.

| Profile | Env | Used by |
|---------|-----|---------|
| `demo` | `VITE_DESK_PROFILE=demo` (or legacy `VITE_LEAN_NAV=true`) | `make demo`, fraud-desk compose |
| `product` | `VITE_DESK_PROFILE=product` | **Dockerfile default** (shipped stack) |
| `brochure` | `VITE_DESK_PROFILE=brochure` (or legacy `VITE_LEAN_NAV=false`) | Optional sales overlay (`docker-compose.demo-vertical.yml`) |

Compatibility: existing `VITE_LEAN_NAV` keeps working. `true` / unset-on-demo-compose → `demo`. `false` → `brochure`. Product image sets `product` and does **not** rely on `LEAN_NAV=false`.

Home:

- `demo` / `product`: Hunt `/graph` if graph URL set, else `/decisions`.
- `brochure`: `/command-center` (unchanged).

## Path sets

### Demo (first hour) — keep today’s lean set

`/decisions`, `/graph`, `/leftovers`, `/rules`, `/observe`, `/ops/shadow`, `/analytics/rule-performance`, `/notifications`, `/settings`, `/help`, plus already-lean ops: `/ops/qa`, `/ops/calibration` (signals plane), `/ops/counters` (signals), `/ops/dispute-deadlines`, `/ops/sar-transport`, `/disputes`. `/cases` list stays hidden. Leftover Hold may deep-link `/cases/:id`.

### Product = demo + analyst jobs that already exist

Add (register routes + sidebar + command palette; do not 404-redirect):

| Path | Job |
|------|-----|
| `/rules/visual` | Visual AST builder (RiskArchitect) |
| `/ops/backtest` | Warehouse backtest jobs |
| `/entity-lists` | Lists for hop `HAS_LIST` |
| `/simulation` | Pack simulation / A-B |
| `/analytics` | Embedded analytics (not exec brochure) |

Planes still hide Advise / calibration chrome when their URL is empty.

### Brochure only (never default on product)

Command Center, `/exec-dashboards`, `/dashboard` classic, `/ops/workload`, `/graph/mule-path`, `/analytics/promo-abuse`, `/analytics/review-rings`, seller-integrity, payout-delay, OSINT pitch, synthetic-identity / social-engineering pages, ML parquet/lifecycle brochure, system-health HUD cluster, `/cases` as a queue.

`/shadow` stays a redirect to `/observe` on all skins (`audit_prod_desk_mocks`).

## A — residual on both skins

### Leftover Brief

On `/leftovers` (and Hunt pack-why strip already shipped):

- Show pack-why / hop status already on the evaluate snapshot (`packWhy.ts`).
- If the leftover case already has a deterministic case-brief comment (`fire_case_brief`), show that text. Do not invent `case.receipt_brief/v1`.
- Fail-close if `GET /v1/leftovers` ≠ 200 (already shipped). Empty queue copy unchanged: REVIEW/DENY mint; ALLOW never.

### Sentence hops

`HAS_LIST` joins `USES_DEVICE` / `HAS_EMAIL` / `HAS_PHONE` / `HAS_CARD` in `sentencePack.ts`. Same shipped etypes. Save still Observe JSON. No new evaluate key.

### BYO-LLM

Demo: TTY skip; desk says LLM off. Product: same four env vars + compose `shadow_agent` when the operator wants the USP. Desk Test / Draft / Observe cards already on `/ops/shadow`. No keys in the SPA.

## Error handling

- Unknown path: demo/product → `leanHomePath()` (Hunt or receipts). Brochure → command center.
- Visual builder without role → existing `/403-unauthorized`.
- Graph URL empty → leftovers hidden; Hunt PlaneOff; leftover Brief still shows pack-why without inventing edges.
- Leftovers API down → no empty-success table.

## Tests

- `leanNav.test.ts`: three profiles. Product shows `/rules/visual` and `/ops/backtest`. Product hides `/command-center` and `/exec-dashboards`. Demo hides visual + backtest. Brochure shows Command Center.
- Dockerfile / fraud-desk / clone-demo: product image `product`; `make demo` `demo`.
- Leftover Brief unit: pack-why line present; no `receipt_brief` schema.
- `sentencePack.test.ts`: `HAS_LIST` emit.
- Do not regress: `test_walk_receipts.py`, leftover fail-close, observe_notify GET-no-write.

## Non-goals

- Role-first persona shells (slice B).
- New velocity runtime, MCP scout folders, first-party Slack/email.
- Unhiding `/cases` as the job.
- Treating brochure as the product default.

## Done when

- `make demo` is still a lean first hour.
- A product image shows visual builder, backtest, lists, simulation, analytics, Hunt, leftovers, Observe, rule-performance, notifications — without Command Center or exec brochure.
- Leftover Brief is pack-why + existing case-brief only.
- Sentence hops include `HAS_LIST`.
- BYO still skippable; keys never in the browser.
