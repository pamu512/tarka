# Live-rule slip (host critic)

**Date:** 2026-08-31  
**Status:** Draft. Plan: `docs/superpowers/plans/2026-08-31-live-rule-slip.md`. Implement **after** [leftover promote HIL](./2026-08-31-leftover-promote-hil-design.md). Sibling of [Observe brain wire](./2026-08-31-observe-brain-wire-design.md) (does not rewrite it).  
**Related:** `rule_precision_after_labels`, `GET /v1/calibration/shadow-promote-gate`, leftover HIL tick, `/ops/shadow`.

## Goal

Name a live `rule_id` when it **opens** (fire-rate change or hit-mix shift). Do **not** treat that as a verdict. Fraud may have left, or fraud may have changed. Park a shadow pack only when **exactly one** hypothesis has support. Live stays `active`. No auto-demote. No auto-promote of the slip draft.

## Scoring lock

Not leftover 3.8 / Hunt 4.0. Not “AI watches live rules.” Seed that flips `active` from a slip ping is a **3**.

## Philosophy

- Drift is a symptom. H1 = hits are now labeled FP (threat left / rule is noise). H2 = leftover fraud missed this rule **and** the hit mix moved (threat changed).
- Both thin, or both supported → ping only. Silence on packs. An analyst does not retire a rule because it got quiet, and does not add a successor because FP rose.
- Same 500-row audit + `y_label` as leftover extras / `rule_precision_after_labels`. No second label math. ALLOW leftover-miss is not recall; say so on the ping.
- Host template only. Advise off still pings and can park. `authored_by=slip_critic`, `is_ai_authored=false`, `mode=shadow`.
- GET has no side effect. Park on the leftover-HIL tick / y_label merge only.
- Promote of a slip pack **adds** that file if leftover + science pass. It does **not** strip the live `rule_id` from another pack. Removing or rewriting the live rule is a human edit (shadow-first demotes that file) or force-live. One leftover still cannot Promote.
- Scout does not own slip. Brain wire does not kill or auto-promote these drafts (`is_ai_authored` stays false).

## What already exists

- `rule_precision_after_labels`: per-`rule_id` labeled hits, `fp_rate`, `enough_support` (min 5).
- Leftover HIL: `shadow-promote-gate` GET, leftover helpfulness, provision FP cap, tick that must not run on GET.
- Scout-pack writes `is_ai_authored=true`. Auto-promote (HIL) only those packs.
- `/ops/shadow` leftover card (HIL). No slip row yet.

## Non-goals

- Auto-demote or edit of a live pack file.
- `replaces_rule_id` on Promote (later slice if we ever strip a live rule in the same verb).
- LLM-authored slip packs. Hunt / leftovers surface. `/v1/brain`. New nav.
- Full recall (ALLOW has no leftover). Graph who-else on the ping.
- Changing evaluate. Changing leftover mint defaults.

---

## Window

Same tenant audit pull as shadow-promote-gate (newest 500, `created_at` desc).

- `current` = first half (newest).
- `prior` = second half.
- Either half `< 50` rows → `window=underpowered`. No pings, no packs.

Join `y_label` `0`/`1` the same way leftover helpfulness does (`trace_id`, then `entity_id`). Proxy labels ignored.

Mix fields (first present wins per row): `event_type` on the audit row; `geo_country`, `device_fingerprint`, `canvas_hash` from `payload_snapshot.payload` (else snapshot top-level). Only these. First-party evaluate fields only if a successor `when` is built.

## Open the ping (union)

For each `rule_id` that appears in `rule_hits` in either half:

**Fire-rate.** `rate = hits / n` in that half. Trigger if `max(hits_current, hits_prior) >= 5` and either:

- `|rate_c - rate_p| >= 0.10`, or
- `rate_p > 0` and `|rate_c - rate_p| / rate_p >= 0.5`

**Mix.** Among rows that **hit** this rule, dominant value per mix field. Trigger if for **any** field both halves have `>= 5` hits with that field present and `dominant_c != dominant_p`.

Either trigger → the rule is on the ping list. Neither → omit.

## Decide (exactly one hypothesis)

`fp_cap` = leftover HIL provision `leftover_fp_rate_cap` if `version >= 1`, else `0.4`.

| Id | Support | Park |
|----|---------|------|
| **H1 retire** | That `rule_id` in `rule_precision_after_labels` has `enough_support` and `fp_rate > fp_cap` | Yes, if H2 is false |
| **H2 successor** | Current half has `>= 5` rows with `y=1` and this `rule_id` **not** in `rule_hits`, **and** mix trigger is true | Yes, if H1 is false |
| Both or neither | — | Ping only (`hypothesis=ambiguous` or `underpowered`) |

H2’s miss count is leftover-born fraud only. Ping field `miss_is_not_recall: true`.

## Park (tick only)

`maybe_park_live_rule_slip(tenant_id)` — same triggers as leftover HIL `maybe_auto_promote_shadow` (y_label merge, scout-pack POST host side, manual tick). **Not** on GET.

Skip park if any `slip_retire_*` / `slip_successor_*` shadow file already has `evidence.live_rule_id` equal to this id. One slot per live rule. Do not rewrite. Human Promote / disable / delete clears the slot. Filenames use `rule_id` sanitized to `[A-Za-z0-9_]` (max 80).

Skip park if the live `rule_id` cannot be found on a loaded `mode=active` pack (H1 needs its `when`). Skip H2 if the dominant mix field of leftover-fraud misses is not an allowed evaluate `when` field — ping stays, `park_reason=no_legal_when`.

### H1 file

```
mode: shadow
is_ai_authored: false
authored_by: slip_critic
name: slip_retire_<rule_id>
rules: one rule, same id, same when as live, score_delta = 5
evidence.slip_kind: retire
evidence.live_rule_id, fp_rate, triggers[], miss_is_not_recall
```

Tightening is **weight**, not a guessed extra `when`. Observe can compare. Live file is unchanged.

### H2 file

```
mode: shadow
is_ai_authored: false
authored_by: slip_critic
name: slip_successor_<rule_id>
rules: one rule, new id `slip_<rule_id>_<token>` (max 80), when: one `eq` on the dominant miss-mix field, score_delta = 15
evidence.slip_kind: successor
evidence.live_rule_id, miss_count, mix_field, mix_value, miss_is_not_recall
```

`score_delta` stays in 5–30. No deny-100.

## GET `live_rule_slip`

Add to `GET /v1/calibration/shadow-promote-gate?tenant_id=` (no write):

```
live_rule_slip: {
  window: "ok" | "underpowered",
  fp_cap: number,
  rules: [{
    rule_id,
    triggers: ["fire_rate" | "mix"],
    hypothesis: "retire" | "successor" | "underpowered" | "ambiguous",
    fp_rate, labeled_hits, miss_count,
    miss_is_not_recall: true,
    parked_draft: str | null,
    park_reason: str | null
  }]
}
```

Scout may see this object. It does not promote from it. If scout-pack would write a file or `name` that matches `slip_retire_*` / `slip_successor_*`, or `evidence.live_rule_id` already has a shadow slip draft → **409** `slip_draft_exists`. Host enforces.

## Desk

`/ops/shadow` only. Card under leftover helpfulness: `rule_id`, triggers, hypothesis, parked draft name or “ping only”. No Override, no Promote-from-row (use the existing draft picker + Promote). Do not put this on Hunt or `/leftovers`.

## Architecture

```
audit 500 ──► split current/prior ──► fire_rate ∪ mix ──► ping list
y_label     ──► rule_precision_after_labels ──► H1
            ──► leftover fraud misses + mix ──► H2
GET shadow-promote-gate ──► live_rule_slip (read)
tick / y_label merge    ──► maybe_park (xor H1/H2) mode=shadow, not ai-authored
Promote                 ──► leftover HIL + science; does not strip live rule
Scout                   ──► 409 if clobber slip draft; kill/auto-promote ignore these files
evaluate                ── unchanged
```

## Files (map, not the plan)

| Area | Where |
|------|--------|
| Pure slip + park helpers | `services/decision-api/src/decision_api/live_rule_slip.py` |
| GET fold | `calibration_api.py` / leftover HIL gate compose |
| Tick hook | same places as `maybe_auto_promote_shadow` |
| Scout clobber 409 | `rule_api.py` scout-pack |
| Card | `OpsShadow.tsx`, `client.ts` |

## Test plan (spec-level)

- Window `< 50` per half → no rules in `live_rule_slip`.
- Fire-rate only → ping; H1/H2 thin → `hypothesis=underpowered`, no file after tick.
- Mix only, H2 green, H1 false → successor file, `mode=shadow`, `is_ai_authored=false`.
- H1 green, H2 false → retire file, same `rule_id`, `score_delta=5`.
- Both green → `ambiguous`, tick writes nothing.
- GET after tick does not write a second file (dedup).
- GET never creates a file.
- Tick does not call `maybe_auto_promote` on slip files.
- Scout-pack onto `slip_retire_*` → 409.
- Promote 200 of a successor does not remove the live rule from the active pack.

## Demo witnesses

1. Live rule fire-rate doubles, labels thin → Observe card names `rule_id`, ping only.
2. Same rule, `>= 5` labeled FP over cap, no H2 → `slip_retire_*` appears in the draft picker. Live evaluate still hits the old weight.
3. Mix shift + `>= 5` leftover fraud misses, H1 false → `slip_successor_*`. Promote (if leftover+science green) adds the successor; old `rule_id` still live.
4. Both H1 and H2 → card says ambiguous, no new file.
5. Advise URL empty → 1–4 still work.

## Out of score (do not claim)

- “The AI retired a live rule.”
- Slip Promote as replace-in-place.
- Brain wire rewritten (footnote only: ignore slip except clobber 409).
- Leftover 3.8 / Hunt 4.0.
- Full-population recall.
