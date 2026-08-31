# Leftover cost + labeled helpfulness on named-draft promote (A3)

**Date:** 2026-08-31  
**Status:** Shipped (leftover cost + helpfulness + desk Promote + provisioned auto-promote + shadow-first writes + `POST …/force-live`). Plan: `docs/superpowers/plans/2026-08-31-leftover-promote-hil.md`.  
**Approach:** A3 (blast radius + SLA/cap hard floor + ack-if-claimed) **plus** leftover-extra FP gate.  
**Related:** [leftover + Hunt production](./2026-08-31-leftover-hunt-production-design.md), [Observe brain wire](./2026-08-31-observe-brain-wire-design.md), VISION.md (LLM authors, humans own live packs via gates), `GET /v1/calibration/shadow-promote-gate`, `GET /v1/leftovers`, `y_label_store`.

## Goal

McNemar going green must not promote into a burning leftover queue **or** a draft whose extra reviews resolve as false positives. A named shadow draft can become live **only** when desk science, leftover **cost**, and leftover-extra **helpfulness** pass.

Scout / the LLM **cannot** promote. After the user’s **first review** provisions auto-promote, decision-api may flip `mode=active` when those **current** user gates pass. If the user later redefines the gates, the next auto-promote uses the new bar — not the AI-stamped one, not the old provision. Default is off. Trend/Wasm `never_auto_promote` is unchanged.

## Scoring lock

This slice is **not** a leftover 3.8 or Hunt 4.0 rescore. Those stay on the leftover/Hunt spec.

This slice is leftover-lead HIL on Observe promote: cost **and** “did the extras help evaluate.” Seed theater without the witnesses below is a **3**. Do not quote no-code because a dashboard row appeared.

## Philosophy (unchanged)

- Decision-api / Rust packs remain sole allow/deny. ML+AI is author + critic, not the hop.
- Evaluate never waits on graph. Leftover list never calls graph.
- ALLOW / `flag` never mint leftovers.
- LLM / Scout writes `mode=shadow` only (`PACK_AUTHOR.md` hard stop). Auto-promote is a **host** action after user provision, not an author action.
- **Shadow-first:** `POST /v1/rules`, `PUT /v1/rules/{file}`, and add-rule persist `mode=shadow`. Omitted `mode` on disk still loads as `active` (fixtures only). Live is Promote, provisioned auto-promote, or human `POST …/force-live`. Scout / assist cannot force-live.
- Humans own the live bar. AI may *propose* gate numbers in pack `evidence`; they never evaluate and never auto-promote until the user copies them into provision (first review).
- Pack lifecycle is not a signals job. `/ops/shadow` is always-on lean, not behind empty `VITE_SIGNAL_API_URL`.
- Not a maker-checker role system. Not draft knobs (B). Not a node editor. Not a Tarka-branded model.

## In the tree

- `desk_promote_gate` requires leftover cost + leftover-extra helpfulness plus labels / McNemar / drift.
- `GET /v1/calibration/shadow-promote-gate` returns `leftover_promote_gate` and `live_rule_slip`.
- Desk `/ops/shadow` leftover card + provision + Promote. Lean always-on.
- Provisioned host auto-promote after first review. Scout still writes `mode=shadow`.
- `PUT …/mode=active` is **409** `shadow_first`. Leftover floor stays on desk Promote. Force-live is the only leftover/science skip.
- Scout `POST /v1/rules/scout-pack` still does not read leftover helpfulness (brain wire is the next spec).
- Leftovers: `GET /v1/leftovers`, claim, promote-ack. Evaluate mint on deny/review by default (`CASE_CREATE_ON_DENY_REVIEW` is opt-out).

## Non-goals

- B: PATCH `score_delta` / outcome band / leftover destination on the draft.
- Forcing Scout / recommender to **read** this gate before authoring (that is [brain wire](./2026-08-31-observe-brain-wire-design.md)).
- VisualRuleBuilder, data-model no-code, NL rule writer.
- New leftover-lead role when the queue is empty.
- Letting Scout or the LLM set `mode=active`, call desk Promote, or call force-live.
- Auto-promoting Wasm / trend drafts (`409 never_auto_promote` stays).
- Auto-ack of leftover claimers. If `leftover_claimer_ack_required` is a blocker, auto-promote waits.
- Auto-demoting a pack that is already `active` when the user tightens gates.
- Pack replay / per-rule blast. Extra counts come from existing CC rows. Per-rule precision stays on `rule_precision_after_labels` for the brain-wire spec.
- Changing evaluate, Hunt, or leftover mint defaults.
- Unhiding `/cases`. FinCEN. Consortium. LLM on evaluate.

## Next specs (not this implementation)

1. [Observe brain wire](./2026-08-31-observe-brain-wire-design.md) — Scout / recommender must read leftover-extra helpfulness before publish; kill FP drafts. **After this spec ships.**
2. [Live-rule slip](./2026-08-31-live-rule-slip-design.md) — host ping + xor park on the same GET/tick. **After this spec ships.** Sibling of brain wire; does not rewrite it.
3. B: knobs on the named draft (`score_delta` 5–30, leftover destination `mint` / `none`), then Promote. Same page.

---

## Named draft

`draft_id` = loaded shadow pack `name` (string, max 256). Must match `get_shadow_packs()`. First name match wins. Duplicate names are an operator problem, not a merge.

- Zero shadow packs → leftover gate still computes queue/SLA/helpfulness; Promote is **404** `no_shadow_draft`.
- One or more → Ops picks `draft_id`. Extra counts and extra labels are the **Observe challenger already on audit**, not a replay of that file. If the named pack is not the one writing `policy_routing`, that is operator error; do not invent a second evaluator.

## Two counts (same 500-row window)

A row counts when both `champion_decision` and `challenger_decision` are non-empty.

| Field | Predicate | Blocks? |
|--------|-----------|---------|
| `extra_review_or_deny` | Champion ∉ {`deny`,`review`} **and** challenger ∈ {`deny`,`review`} | Display only (volume) |
| `extra_leftover_mint` | Same rows **and** `CASE_CREATE_ON_DENY_REVIEW` is on | Yes, if `> cap` |

`flag` / `allow` never mint. Champion already `deny`/`review` → not extra leftover (queue already paid).

If mint is **off**, `extra_leftover_mint` is **0**. Still show `extra_review_or_deny` so Ops sees volume.

`rows_with_policy_routing == 0` → both extras are 0, hint `no_observe_pairs`. That does **not** block leftover_promote_gate by itself (science gates already starve).

**Volume cap default:** `10` (`LEFTOVER_PROMOTE_ADD_CAP`). After first review, the **provision** integer wins. Env is only the pre-review default.

## Helpfulness (labeled extras)

Population = the `extra_review_or_deny` rows. Join durable `y_label` the same way as `labeled_champion_challenger_f1`: `y_label_store` `by_trace` then `by_entity`. Proxy-from-decision labels **do not** count (`0`/`1` from leftover resolve / QA only).

| Field | Meaning |
|--------|---------|
| `labeled_extras` | Extra rows with `y_label` in {`0`,`1`} |
| `extra_tp` | Those with `1` (FRAUD: `CONFIRMED_FRAUD`, `ACCOUNT_TAKEOVER`, `FRIENDLY_FRAUD`, `SAR_FILED`) |
| `extra_fp` | Those with `0` (LEGITIMATE: `FALSE_POSITIVE`, `CUSTOMER_CLEARED`, `INSUFFICIENT_EVIDENCE`) |
| `fp_rate` | `extra_fp / labeled_extras` when `labeled_extras > 0`, else `null` |

**FP cap default:** `0.4` (`LEFTOVER_PROMOTE_FP_RATE_CAP`).  
**Min labeled extras default:** `5` (`LEFTOVER_PROMOTE_MIN_LABELED_EXTRAS`).  
After first review, provision numbers win. Env is only the pre-review default.

### When helpfulness blocks

| Blocker | When |
|---------|------|
| `leftover_extras_fp_over_cap` | `labeled_extras >= min` **and** `fp_rate > fp_cap` |
| `leftover_extras_no_lift` | `labeled_extras >= min` **and** `extra_tp == 0` **and** `extra_fp >= min` |

### When helpfulness does **not** block

- `labeled_extras < min` → `underpowered: true`, hint `helpfulness_underpowered`. Cost gates still apply. Do not invent precision. Do not fail-closed on unlabeled extras (new tenants would never promote).
- Zero extras → no helpfulness blocker, hint `no_observe_pairs` or `queue_empty` as appropriate.
- Labeled CC F1 (champion vs challenger on **all** labeled rows) stays diagnostic. It is **not** a leftover-extra blocker and does not replace this join.

## Leftover promote gate

Pure function + leftover list fetch + `y_label_store` (already in-process on decision-api). Fold into `desk_promote_gate.requires` as `leftover_promote_gate`.

`desk_promote_gate.promote_allowed` is true only when labels, McNemar, drift, **and** leftover (cost + helpfulness) all have empty blockers.

### Inputs

- `tenant_id` (required for leftover fetch; same query as today’s shadow-promote-gate)
- CC rows already loaded for McNemar
- `CASE_CREATE_ON_DENY_REVIEW`
- `GET /v1/leftovers?tenant_id=` (S2S, existing `CASE_API_URL` + `CASE_INTERNAL_TOKEN`)
- `load_y_labels(tenant_id)` (same store leftover resolve already writes)
- ack row for `(tenant_id, draft_id)` when `draft_id` is present
- volume cap, FP cap, min labeled extras (provision if `version >= 1`, else env defaults)

### Blockers (any one)

| Blocker | When |
|---------|------|
| `leftover_queue_unavailable` | `CASE_API_URL` unset **or** leftovers GET fails / non-2xx. **Fail closed.** Do not promote blind. |
| `leftover_sla_breached` | Any leftover in the list has `sla_breached=true`. |
| `leftover_add_over_cap` | `extra_leftover_mint > volume cap`. |
| `leftover_claimer_ack_required` | At least one leftover has non-blank `claimed_by` **and** no **valid** ack for this `draft_id`. |
| `leftover_extras_fp_over_cap` | Helpfulness FP rule above. |
| `leftover_extras_no_lift` | Helpfulness no-lift rule above. |

Empty leftover queue + mint off + no claimers + underpowered helpfulness → leftover **cost** green, leftover **helpfulness** not blocking. Science may still fail.

### Ack validity

Ack is valid only if `acked_by` is still in the current `claimed_by` set for that tenant.

Release / resolve that clears the claimer **invalidates** the ack. Re-ack required if any leftover is still claimed (by anyone).

Ack is **not** required when no leftover is claimed (including empty queue). Do not invent a leftover-lead role.

Resolve that writes `y_label` is what **feeds** helpfulness. Ack does not substitute for a label.

### Payload (on shadow-promote-gate)

```
leftover_promote_gate: {
  schema_id: "tarka.leftover_promote_gate/v1",
  promote_allowed: bool,
  blockers: [str],
  extra_review_or_deny: int,
  extra_leftover_mint: int,
  leftover_mint_on: bool,
  cap: int,
  sla_breached_count: int,
  leftover_count: int,
  claimers: [str],
  ack_required: bool,
  ack: { draft_id, acked_by, acked_at } | null,
  helpfulness: {
    labeled_extras: int,
    extra_tp: int,
    extra_fp: int,
    fp_rate: float | null,
    fp_rate_cap: float,
    min_labeled_extras: int,
    underpowered: bool
  },
  hint: str
}
```

`hint` examples: `no_observe_pairs`, `mint_off_extras_are_display_only`, `queue_empty`, `helpfulness_underpowered`.

When `tenant_id` is missing, leftover fetch is skipped → blocker `leftover_queue_unavailable`. Do not treat missing tenant as green leftover. S2S leftover GET uses existing `X-Internal-Token` (same as evaluate mint). Helpfulness without tenant is underpowered (no labels to join); missing tenant still fail-closes via queue unavailable.

## Case-api: ack

New table `leftover_promote_acks`:

| Column | Type | Rules |
|--------|------|--------|
| `tenant_id` | string, not null | |
| `draft_id` | string(256), not null | Shadow pack `name` |
| `acked_by` | string(256), not null | Actor id |
| `acked_at` | timestamptz, not null | |

Unique `(tenant_id, draft_id)`. Upsert on re-ack.

Actor = existing leftover actor (`X-Actor-Id` or `get_current_user().user_id`).

`POST /v1/leftovers/promote-ack` body `{ "tenant_id", "draft_id" }`

- Actor currently claims ≥1 leftover for that tenant → 200, upsert ack.
- Actor claims none → **403** `{ "detail": "not_a_claimer" }`.
- `draft_id` blank → 400.

`GET /v1/leftovers/promote-ack?tenant_id=&draft_id=`

Returns `{ "ack": { draft_id, acked_by, acked_at } | null, "claimers": [str], "required": bool }`.

`required` = at least one leftover claimed. Auth: same as leftover list (`analyst` or insecure desk).

Decision-api does **not** store acks. Decision-api **does** already store `y_label`; do not duplicate labels on case-api.

## Provision (first review + redefine)

Tenant-scoped file next to `y_label_store` (same path hygiene / content-addressed tenant token). Not a CRM table.

```
{
  schema_id: "tarka.shadow_auto_promote_provision/v1",
  tenant_id: str,
  auto_promote: bool,          // default false until first review sets true
  leftover_add_cap: int,       // default 10
  leftover_fp_rate_cap: float, // default 0.4
  min_labeled_extras: int,     // default 5
  provisioned_by: str,
  provisioned_at: str,
  version: int                 // increment on every save
}
```

**First review:** user saves this once on `/ops/shadow` (analyst). That is “gates defined.” `auto_promote: true` is the provision that allows host auto-promote. Saving gates with `auto_promote: false` still locks the numbers; Promote stays human-only.

**Redefine:** same PUT, new `version`. In-flight `mode=shadow` drafts are judged on the **new** numbers next tick. Already-`active` packs are not auto-reverted.

**Hard floors the user cannot turn off:** `leftover_queue_unavailable`, `leftover_sla_breached`, leftover helpfulness blockers, existing desk science (labels / McNemar / drift). Provision only changes the three numbers and the auto-promote switch.

**AI-stamped gates** (pack `evidence.proposed_gates` or similar) are display-only. A “use scout numbers” control copies them into the PUT body. Until that copy, they do not apply.

`GET /v1/rules/shadow-auto-promote-provision?tenant_id=` → current file or defaults + `auto_promote: false` + `version: 0` (never provisioned).

`PUT /v1/rules/shadow-auto-promote-provision` body as above minus `provisioned_*` / `version` (server sets). Actor = leftover/desk actor.

No provision (`version: 0` or `auto_promote: false`) → auto-promote never runs.

## Auto-promote (host, after provision)

Scout still cannot call desk Promote or set `mode=active`.

Decision-api `maybe_auto_promote_shadow(tenant_id)`:

1. Load provision. If missing / `auto_promote` is false → no-op, reason `not_provisioned`.
2. Recompute leftover_promote_gate **using provision numbers** + desk science. If any blocker → no-op (including `leftover_claimer_ack_required` — no auto-ack).
3. For each loaded pack with `mode=shadow` and `is_ai_authored=true`, same write as desk Promote (`mode=active`, `load_rules()`, rule-change `auto_promote_shadow_pack` with `provision.version`, `actor=auto_promote`).
4. Human-authored shadow canaries are not auto-promoted.

**Triggers (no cron in this slice):** after `POST /v1/rules/scout-pack` succeeds (server-side, not the scout client); after `y_label` merge for that tenant. `GET` shadow-promote-gate must **not** promote.

`POST /v1/rules/shadow-packs/auto-promote-tick?tenant_id=` (analyst / internal) is the same function for tests and a later scheduler. 200 `{ "auto_promote": true|false, "promoted": [draft_id], "reason": str | null, "leftover_promote_gate", "desk_promote_gate" }`.

## Promote (the action leftover can stop)

Desk: `POST /v1/rules/shadow-packs/{draft_id}/promote?tenant_id=`  
Role: `analyst` (same as shadow-promote-gate). **No** governance secret.

1. Resolve `draft_id` to a loaded shadow pack (`name` match). 404 if missing.
2. Recompute leftover_promote_gate (cost + helpfulness) + existing desk science for that tenant. If any blocker → **409** `{ "detail": "promote_blocked", "desk_promote_gate", "leftover_promote_gate" }`.
3. Set that pack file `mode=active`, `load_rules()`, append rule-change `promote_shadow_pack`.
4. 200 `{ "promoted": true, "draft_id", "file", "mode": "active" }`.

`PUT /v1/rules/{filename}/mode` with `mode=active` **must** run leftover_promote_gate (cost **and** helpfulness). Pass `tenant_id` as a query param. Missing tenant, case-api down, SLA, volume cap, missing valid ack, FP over cap, or no-lift → **409** `leftover_promote_gate` (fail closed, including the governance-secret path). Labels/McNemar/drift stay desk-Promote-only so existing scripts do not inherit the science bar.

`mode=shadow` / `disabled` unchanged.

Scout / AI author still cannot call this. `PACK_AUTHOR.md` hard stop stays. Host auto-promote above is the only non-human path, and only when provisioned.

## Shadow-first create / edit

A rule is not live until Observe has seen it, unless a human **force-lives**.

| Write | Persist |
|-------|---------|
| `POST /v1/rules` | Always `mode=shadow`. Ignore client `mode` if added later. |
| `PUT /v1/rules/{file}` | Always `mode=shadow` (demotes a live pack). Content change is a new shadow draft of that file. |
| `POST /v1/rules/{file}/rules` | If the pack was `active`, set `mode=shadow` after the add. |
| `POST /v1/rules/scout-pack` | Already `mode=shadow`. Unchanged. |
| Vertical install | Lands `mode=shadow` unless the filename is on the **fixture allowlist** (repo seed packs at first boot only). |

Evaluate loaders (`json_rules`, `pack_evaluator`, `policy_set`) keep omitted-mode = `active` for **on-disk fixtures only**. API writes must set the field.

## Force-live (user override)

Different verb from Promote. Promote still requires `desk_promote_gate`. Force-live skips leftover + science and still requires a human fingerprint.

`POST /v1/rules/{filename}/force-live`

- Role: same governance secret as other rule writes + `X-Actor` required (non-empty).
- Body: `{ "reason": str }` (`reason` min 8 chars).
- Scout / assist / missing actor → **403** `force_live_human_only`.
- Sets `mode=active`, `load_rules()`, appends rule-change **`rule_force_live`** `{ actor, reason, file, prior_mode }`.
- 200 `{ "mode": "active", "forced": true, "file" }`.

Desk: Override is a second control on Observe, smaller than Promote, reason required. Show last `rule_force_live` on the pack. Do not put Override on Hunt.

`PUT …/mode=active` without going through Promote or force-live is **409** `shadow_first` (leftover floor stays for Promote; force-live is the only skip).

## Desk

- Add `/ops/shadow` to `LEAN_NAV_PATHS` and `isProductionSurfacePath`.
- `planeForPath("/ops/shadow")` stays **null** (not `signals`). Visible when lean is on, even if `VITE_SIGNAL_API_URL` is empty.
- `/leftovers` visibility unchanged (graph on).
- Page: leftover card above existing science — extras, SLA count, claimers, **helpfulness**, draft picker, Ack, Promote, **first-review provision** (the three numbers + `auto_promote` checkbox + last `version` / `provisioned_by`). Optional “use scout proposed gates” copies `evidence.proposed_gates` into the form; it does not save until the user PUTs.
- Promote stays available when `auto_promote` is false. When true, Promote is still valid (human can force the same path). Disabled when `desk_promote_gate.promote_allowed` is false. Show blockers as text, not a second CRM.
- Do not port L3 off the page in this slice.

## Architecture

```
Observe audit (500) ──► extra_review_or_deny / extra_leftover_mint
                    └──► extras ⋈ y_label_store ──► extra_tp / extra_fp / fp_rate
GET /v1/leftovers   ──► sla_breached_count, claimers
GET promote-ack     ──► ack valid iff acked_by ∈ claimers
                 └──► leftover_promote_gate ──► desk_promote_gate
POST leftovers/promote-ack   (claimer only)
Hunt resolve        ──► y_label (already) ──► helpfulness + auto-promote tick
PUT  shadow-auto-promote-provision          ──► user bar (first review / redefine)
maybe_auto_promote  ──► mode=active iff provision.auto_promote && desk_ok
POST rules/shadow-packs/{draft_id}/promote  ──► same write, human
PUT  rules/{file}/mode=active               ──► 409 shadow_first
POST rules/{file}/force-live                ──► human reason → active + rule_force_live
POST/PUT rules                              ──► always persist mode=shadow
```

Evaluate path is untouched. Leftover list still does not call graph.

## Files (map, not the plan)

| Area | Where |
|------|--------|
| Extra counts + extra label join | `champion_challenger_audit.py` (pure helpers from existing CC rows + `load_y_labels`) |
| Leftover gate | `calibration_api.py` shadow-promote-gate + small leftover_promote_gate module |
| Leftover S2S | existing `CASE_API_URL` / `CASE_INTERNAL_TOKEN` (same as mint) |
| Ack + alembic | case-api |
| Desk promote + provision + auto-promote tick | `rule_api.py` + small provision file next to `y_label_store` |
| Shadow-first writes + force-live | `rule_api.py` create/update/add-rule + `POST …/force-live` |
| Lean + card | `leanNav.ts`, `OpsShadow.tsx`, `client.ts` |

Do not reimplement `rule_precision_after_labels` here. Brain wire reuses this gate’s `helpfulness` object.

## Test plan (spec-level)

- Extra: allow→review counts; deny→review does not; mint off ⇒ `extra_leftover_mint=0` while display count stays.
- SLA leftover ⇒ leftover gate false; empty queue + no claimers ⇒ leftover cost green (science may still fail).
- Case-api down / URL unset ⇒ `leftover_queue_unavailable`, desk_ok false.
- Ack 403 if actor claims nothing; 200 upsert if they claim; ack stale after that actor’s claim clears.
- Helpfulness: 5 extras labeled `0` ⇒ `leftover_extras_fp_over_cap`; 5 extras labeled `1` ⇒ no FP blocker; 3 labeled extras ⇒ `underpowered`, no FP blocker; 5 extras labeled `0` and `extra_tp=0` ⇒ `leftover_extras_no_lift` (may stack with FP).
- Proxy labels do not increment `labeled_extras`.
- Desk Promote 409 when leftover (cost or helpfulness) or science blocked; 200 sets `mode=active` only when all green.
- `PUT …/mode=active` 409 on leftover SLA **or** FP-over-cap even with governance secret.
- `POST /v1/rules` and `PUT /v1/rules/{file}` persist `mode=shadow`. A live pack that is edited becomes shadow.
- `POST …/force-live` without actor or reason 403/422. With actor+reason 200 and a `rule_force_live` change row. Scout token 403.
- After force-live ships: `PUT …/mode=active` 409 `shadow_first`.
- Provision default `auto_promote=false`; tick no-ops with `not_provisioned`. After PUT `auto_promote=true` and desk_ok, tick promotes `is_ai_authored` shadow packs only.
- User PUT tighter `leftover_fp_rate_cap`; tick uses new cap (old scout `evidence.proposed_gates` ignored).
- Tick does not promote when `leftover_claimer_ack_required`. GET shadow-promote-gate does not promote.
- Lean: `/ops/shadow` in `LEAN_NAV_PATHS`; `planeForPath` is not `signals`; visible with empty signal URL.

## Demo witnesses

1. Tenant with one SLA-breached leftover. Science may be green in fixture. Promote 409 `leftover_sla_breached`. Queue still on `/leftovers`.
2. Mint on, Observe rows with allow→review over volume cap. Promote 409 `leftover_add_over_cap`. Card shows both extras.
3. One leftover claimed by actor A. Actor B Promote 409 `leftover_claimer_ack_required`. Actor A Ack → B can Promote if science **and** helpfulness are green.
4. Empty leftovers, mint off, helpfulness underpowered. Leftover cost green. Promote still follows labels/McNemar/drift.
5. Five Observe extras resolved `FALSE_POSITIVE` (`y_label=0`). Promote 409 `leftover_extras_fp_over_cap`. Card shows `extra_fp=5`.
6. Five Observe extras resolved `CONFIRMED_FRAUD`. Helpfulness does not block. Promote still follows science + cost.
7. Lean build, empty `VITE_SIGNAL_API_URL`. `/ops/shadow` in the nav. Not a “plane off” page.
8. First review: save provision `auto_promote=true` with defaults. Later a green AI shadow pack auto-promotes on y_label merge / scout-pack POST. Scout response is still `mode=shadow`; host write is `active`.
9. User redefines `leftover_add_cap` to `0` while extras would mint. Tick no-ops (`leftover_add_over_cap`). Human Promote 409. Live packs stay live.
10. Create a pack via `POST /v1/rules`. Live evaluate does not hit it. Observe does. Force-live with a reason; then it hits live. Change the pack via `PUT`; it is shadow again until Promote or force-live.

## Out of score (do not claim)

- Two-person leftover-lead when the queue is empty (that is A2).
- Ops can change a threshold without opening JSON (that is B).
- Scout refuses to author because leftovers were FP (that is brain wire).
- Silent auto-promote with `version: 0` / `auto_promote: false`.
- Wasm / trend auto-promote.
- `promote_live_claim_allowed` or LIVE label claims. Unchanged.
- Leftover 3.8 / Hunt 4.0 as live product scores (other spec; production witnesses still required there).
- “AI is the live brain.” Evaluate is still Rust.
- Quiet `PUT …/mode=active` after force-live ships (must be `shadow_first`).
- API create with omitted `mode` staying live (must write `shadow`).
