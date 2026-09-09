# Analyst control loop

One desk path. No buyer-demo theater.

## Investigator path

Decisions is the receipt list: what the pack decided and which pack fired, in plain English. Open a row for why. You do not need pack UUIDs.

REVIEW or DENY leaves a leftover. Next legal actions: Open receipt, Create Observe draft, or disposition on Hunt. ALLOW never leaves a leftover.

Leftovers are residual, not a case CRM. Evaluate still decides in Rust.

1. **Leftover / HIL / FP** — `/leftovers` is residual. Work happens on Hunt (`/graph`). FP late-label mints a soften Observe draft.
2. **Draft** — leftover/HIL → L2 draft (`mode=shadow`). Typed leftover why is ≥8 characters; the leftover brief is not the why. After save, why stays on leftover — no `/ops/shadow` detour. Duplicate mint returns `409 draft_exists` — open the existing draft. Sentence pack on Observe emits the same JSON; legacy canvas is not a product SKU.
3. **Backtest / skip** — AI drafts require replay pass. Human skip needs actor + reason.
4. **Observe** — `/ops/shadow`. Bake-off strip is numbers only. LoopScoreboard / `/ops/bakeoff` = tenant globals.
5. **Promote** — ungated → human Promote confirm (pack name, becomes live, Cancel leaves Observe). Confirm shows pack `rule_hit_rate` / `shadow_divergence` or honest empty; thresholds are tenant policy. Gates defined+met → may auto-Promote (default off). Model never Promotes.
6. **Propose Demote** — ObserveEase: Ready to Promote / Suggest Demote (tick numbers → existing Propose, never Confirm) / Live packs. Active pack → Propose → Confirm. Promote undo is this shortcut. Model never demotes.

Queue connectors (if `QUEUE_WEBHOOK_URL` is set) notify the buyer’s existing CX tool. Leftovers are not a case CRM.

Hunt `/graph` is Day-1 Path B depth-1. Empty `GRAPH_SERVICE_URL` is UX0 `PlaneOff`, not invented neighbors. See [graph-analysis — Day-1 Hunt depth](graph-analysis.md#day-1-hunt-depth) and [hunt-depth-v1](../../contracts/hunt-depth-v1.md).

Promote undo = Propose Demote (then Confirm). See [pack-gitops](pack-gitops.md) and [pack-promote-export-v1](../../contracts/pack-promote-export-v1.md): desk Promote is live SoT; git is export.

Global mix vs per-pack Promote: [bakeoff-sop](bakeoff-sop.md#where-to-read-numbers-d8-vs-m3).

See [bakeoff-sop](bakeoff-sop.md), [queue-seam-sop](queue-seam-sop.md), [desk UI scorecard](desk-ui-scorecard.md) (T1–T6 clicks/steps).
