# Claim lock (honesty)

**Rule:** Do not advertise live-tenant, certified SOC2/PCI, or product-wide maturity scores from fixture CI, waived partner proofs, or deleted score matrices.

## Allowed language

- Offline / fixture holdouts and golden corpora prove **wiring and gates**, not named live tenants.
- **Observe** = observe-only evaluate (`metadata.shadow`) + pack canary; **Advise** = LLM copilot (investigation, Shadow agent, trend) — advise only, never decides. decision-api **decides**.
- Partner fusion and enrichment are honest only when credentials and sinks are real; otherwise degrade (503 / WAIVED), never invent success.
- Vertical packs and kill-criteria gates are installable locally; empty tenant ≠ demo SHA proof.

## Source of truth

| Topic | Doc |
|-------|-----|
| Feature authority | [`docs/docs/guides/feature-data-flows.md`](../docs/guides/feature-data-flows.md) |
| AI / trend ops | [`docs/docs/guides/repo-productionization-runbook.md`](../docs/guides/repo-productionization-runbook.md) |
| Control narrative (not a cert) | [`soc2-pci/`](./soc2-pci/) |

Historical “maturity 4.x” scorecards and competitive matrices were removed in the docs cleanup.

## Tip claims (after #392–#397)

Buyer-facing README / Day-1 / hop / GNN copy must match this table. Do not advertise the right-hand column as shipped.

| True on tip | Must not read as shipped |
|-------------|--------------------------|
| ELv2 source-available (not OSS). Beta, no GA | Open-source; ready-for-beta testers; unattended merchant beta |
| `make doctor && make demo`. Rust evaluate + receipts + pack-why | Model ALLOW / DENY; Tarka-branded model |
| Observe ≠ live. Human Promote. Founder-in-the-loop | Live hop FLAG without Promote; auto-Promote; auto-demote |
| Hop packs `mode=shadow`. Live overlay only via pack Promote | Always-on graph; “every evaluate is on the graph”; GNN live / GNN god-model |
| Empty `GRAPH_SERVICE_URL` ≠ sibling identity (`graph:missing`) | Closed omniscient AI author loop |
| L2 leftover/override → Observe draft; AI backtest **required** before Observe | Case CRM |
| FP late-label → Observe soften draft (#394) | Consortium SKU |
| Beachhead Observe seeds (promo / COD / payout) seed ≠ live. Not banks | Users / LOI / ARR as traction |
| Graph-risk / ring-score challenger (#397). `GRAPH_GNN_BETA_URL` unset in compose | GNN live |
