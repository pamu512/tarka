# Analyst control loop

One desk path. No buyer-demo theater.

1. **Leftover / HIL / FP** — `/leftovers` is residual. Work happens on Hunt (`/graph`). FP late-label mints a soften Observe draft.
2. **Draft** — leftover/HIL → L2 draft (`mode=shadow`). Duplicate mint returns `409 draft_exists` — open the existing draft.
3. **Backtest / skip** — AI drafts require replay pass. Human skip needs actor + reason.
4. **Observe** — `/ops/shadow`. Bake-off strip is numbers only.
5. **Promote** — ungated → human Promote confirm (pack name, becomes live, Cancel leaves Observe). Pack metrics stay blank until the pack-metrics API fills them. Gates defined+met → may auto-Promote (default off). Model never Promotes.
6. **Propose Demote** — Active pack → Propose → Confirm. Promote undo is this shortcut. Model never demotes.

Queue connectors (if `QUEUE_WEBHOOK_URL` is set) notify the buyer’s existing CX tool. Leftovers are not a case CRM.

Promote undo = Propose Demote (then Confirm). See [pack-gitops](pack-gitops.md): desk Promote is live SoT; git is export.

See [bakeoff-sop](bakeoff-sop.md), [queue-seam-sop](queue-seam-sop.md).
