# Observe brain wire (Scout / recommender reads leftover helpfulness)

**Date:** 2026-08-31  
**Status:** Draft — implement **after** [leftover promote HIL](./2026-08-31-leftover-promote-hil-design.md) ships.  
**Depends on:** leftover_promote_gate `helpfulness` object + extra-row join (same spec).  
**Related:** VISION.md add-on (scout writes, parks in Observe, humans own live via gates), `PACK_AUTHOR.md`, `scout_pack_publisher.py`, `rule_recommender.py`, `rule_precision_after_labels`, [live-rule slip](./2026-08-31-live-rule-slip-design.md) (sibling; host critic of live `rule_id`s).

## Goal

ML+AI is the **author and critic**, not the hop. After leftover resolve writes `y_label`, the next shadow draft must **see** those labels. A draft whose leftover extras are false positives must not be re-published.

Scout still cannot set `mode=active` and cannot call evaluate as the decider. If the user already provisioned auto-promote on leftover HIL (first review), decision-api may promote after this publish using the **current** user gates. If the user redefines gates, the next tick uses those — not scout `evidence.proposed_gates`.

## Why this is a second spec

Leftover promote HIL **stops the ship**. This spec **steers the writer**. Folding both into one plan would mix case-api ack / lean Promote with shadow_agent publish. Ship the gate first so this wire has a real payload to read.

## Scoring lock

This is not leftover 3.8 / Hunt 4.0. Not “we have an LLM.” Seed that publishes a scout pack without a leftover-helpfulness read is a **3**.

## Philosophy (unchanged)

- Rust packs on evaluate. No Tarka-branded model. No LLM on the live hop.
- `mode` on AI-authored **writes** stays `shadow` (`PACK_AUTHOR.md` hard stop 1–2). Host auto-promote (leftover HIL provision) is the only path to `active` without a human Promote click or human force-live. Scout cannot force-live.
- Same leftover-extra population and FP / no-lift rules as leftover_promote_gate. Do not invent a second label math.
- Silence is allowed. If leftovers say the last draft hurt, do not emit another pack.

## What already exists

- Hunt resolve → `_persist_disposition_y_label` → `y_label_store`.
- Leftover promote HIL (once shipped): extras ⋈ labels → `helpfulness` on shadow-promote-gate.
- `rule_precision_after_labels` (min 5 labeled hits, `y` `0`/`1`).
- Scout `publish_scout_pack` → `POST /v1/rules/scout-pack` with no leftover read.
- `rule_recommender` mines historical decisions; it does not take leftover extras as a hard stop.
- In-process scout fingerprint dedup only (`_published_fingerprints`).

## Non-goals

- Scout / LLM calling Promote or writing `mode=active`.
- Auto-promoting Wasm / trend (`never_auto_promote`).
- Draft knobs (B). VisualRuleBuilder. NL rule writer.
- New endpoint if shadow-promote-gate already returns `leftover_promote_gate.helpfulness` **and** `rule_precision_after_labels` can ride the same GET (add the rules array there if missing; do not add `/v1/brain`).
- Changing evaluate. Changing leftover mint defaults. Maker-checker roles.
- Owning live-rule slip. If `live_rule_slip` is on the GET, Scout does not promote from it and does not treat a ping as leftover helpfulness. Host returns **409** `slip_draft_exists` if scout-pack would clobber a slip draft. Kill / auto-promote stay `is_ai_authored` only (slip drafts are host templates).

---

## Read (one GET)

Scout and recommender call existing `GET /v1/calibration/shadow-promote-gate?tenant_id=`.

Required fields after leftover HIL:

- `leftover_promote_gate.helpfulness`
- `leftover_promote_gate.blockers` (at least the two helpfulness blockers)
- `rule_precision_after_labels` (add to this GET in this slice if not already present — reuse the function, same 500-row export + `y_label` join)

If leftover HIL is not deployed, this spec does not ship. Do not re-join extras in shadow_agent.

`tenant_id` comes from the scout hypothesis / recommend request. If missing: **do not publish** (`reason: leftover_helpfulness_no_tenant`). Observe without a tenant cannot be a brain.

S2S: scout already hits decision-api. Analyst/internal token as today’s scout-pack POST. No case-api call from scout.

## Write hard stops (publish / recommend)

Before `POST /v1/rules/scout-pack` or emitting a recommendation:

| Condition | Action |
|-----------|--------|
| Helpfulness blocker `leftover_extras_fp_over_cap` | Drop. `reason: leftover_extras_fp_over_cap` |
| Helpfulness blocker `leftover_extras_no_lift` | Drop. `reason: leftover_extras_no_lift` |
| Proposed `rule.id` appears in `rule_precision_after_labels.rules` with `enough_support` and `fp_rate` > leftover FP cap (`0.4` / `LEFTOVER_PROMOTE_FP_RATE_CAP`) | Drop that rule. If no rules remain, drop the pack. `reason: rule_fp_over_cap` |
| `helpfulness.underpowered` | Publish **allowed**. Pack `evidence.leftover_helpfulness` must copy `{ labeled_extras, extra_tp, extra_fp, hint: helpfulness_underpowered }`. |
| Gate GET fails | Drop. `reason: leftover_helpfulness_unavailable`. Fail closed on the writer, same as promote fail-closed on the queue. |

Deterministic scout template and LLM author share this check. Validation failure still returns `None` / not published.

Do **not** drop solely because leftover **cost** blockers are set (`leftover_sla_breached`, `leftover_add_over_cap`, `leftover_claimer_ack_required`). Those stop Promote, not authorship. A new draft may be the fix. Helpfulness / per-rule FP is the critic.

## Kill (existing shadow draft)

Helpfulness extras are **tenant-level** (one Observe challenger, no per-file replay). When leftover_promote_gate has `leftover_extras_fp_over_cap` or `leftover_extras_no_lift`:

- Set every loaded pack with `mode=shadow` **and** `is_ai_authored=true` to `mode=disabled`. Human-authored shadow canaries stay up.
- Append rule-change `kill_shadow_pack_leftover_fp` per file with `helpfulness`.
- Each pack’s scout fingerprint (existing `_fingerprint_key` / evidence) goes in a **durable** killed set so in-memory dedup cannot republish after process restart.

Kill is decision-api’s job on the shadow-promote-gate compute **or** a thin internal function both the GET and scout-pack POST call. Do not add a desk “Kill” CRM. Ops sees `mode=disabled` on the draft picker.

Scout cannot re-enable. Human Promote on a disabled pack is **404** / not a shadow draft.

## Recommender

`POST /v1/recommendations` already takes `tenant_id`. After generating candidates, filter with the same rule-FP hard stop. Return `dropped: [{ rule_id, reason }]` so the desk can see the critic. Do not write an active pack. Existing recommend → optional pack append stays behind whatever governance it already uses; this spec only filters the suggestion list.

## PACK_AUTHOR.md

Add hard stop:

8. **You must not ignore leftover helpfulness.** If the host injects `leftover_helpfulness` / per-rule FP into the author context and blockers fire, return no pack (empty submit). You still cannot promote. Optional `evidence.proposed_gates` is a suggestion for the user’s first review; the host never applies it.
9. **You cannot provision auto-promote.** That PUT is human-only on leftover HIL.

Host (publisher) enforces this even if the LLM ignores the prompt. After a successful scout-pack POST, the host may run leftover HIL `maybe_auto_promote_shadow` — still not the author.

## Desk

No new lean page. `/ops/shadow` leftover card already shows helpfulness. After kill, draft picker lists the pack as disabled. Do not add Advise chrome.

## Architecture

```
Hunt resolve ──► y_label_store
shadow-promote-gate ──► leftover_promote_gate.helpfulness
                     └──► rule_precision_after_labels
scout / recommender ──GET──┘
         │ drop if extras FP / no-lift / rule FP
         │ stamp evidence if underpowered
         └── POST scout-pack mode=shadow only
              └── host maybe_auto_promote (iff user provision.auto_promote && current gates pass)
kill: extras FP on current draft ──► mode=disabled + durable fingerprint
Human Promote / host auto-promote (HIL spec) ──► mode=active iff desk_ok
evaluate ── unchanged, Rust
```

## Test plan (spec-level)

- Publisher GET mocked with `leftover_extras_fp_over_cap` → no POST scout-pack.
- Underpowered helpfulness → POST happens, pack `evidence.leftover_helpfulness.hint == helpfulness_underpowered`.
- Missing tenant_id → no publish.
- Gate GET 5xx → no publish.
- Proposed rule_id with `enough_support` and `fp_rate=0.8` → that rule stripped; empty rules → no publish.
- SLA-breached leftover **without** helpfulness blockers → publish still allowed.
- Current shadow draft + FP-over-cap → pack file `mode=disabled`; second publish of same fingerprint dropped after process restart (durable kill).
- `PACK_AUTHOR.md` / contract test: LLM cannot set `mode=active` (regression).
- After publish, if leftover HIL provision `auto_promote=true` and gates green, pack file becomes `active` via host tick (not the scout JSON). If provision off, file stays `shadow`.

## Demo witnesses

1. Five extras labeled `FALSE_POSITIVE`. Scout burst that would publish → `published: false`, reason `leftover_extras_fp_over_cap`. Existing shadow pack disabled.
2. Underpowered (0–4 labeled extras). Scout template still publishes `mode=shadow` with evidence stamp. Auto-promote follows leftover HIL provision (off → stays shadow; on + science green → host may activate).
3. Recommend API: a high-FP rule in `rule_precision_after_labels` does not appear in the kept list; `dropped` names `rule_fp_over_cap`.
4. Evaluate a payment after a killed draft: live pack unchanged (disabled is not active).

## Out of score (do not claim)

- “AI decides live traffic.”
- Auto-promote without leftover HIL provision / first review.
- Auto-promote against scout-proposed gates after the user redefined provision.
- Leftover 3.8 / Hunt 4.0.
- Marble no-code.
- Brain works if leftover HIL helpfulness is not in production (this spec is blocked on that).
