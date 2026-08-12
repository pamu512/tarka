# Tarka Wiki

Operator mirror of the docs hub. If this wiki and `docs/` disagree, **trust `docs/INDEX.md` and the code**.

## Start here

| Page | Purpose |
|------|---------|
| [Quickstart](Quickstart) | Lite / fraud-desk → first evaluate |
| [Architecture](Architecture) | Services, stores, authority |
| [Services](Services) | What each process does |
| [Rules and Simulation](Rules-and-Simulation) | Packs, backtest, promote |
| [Operations](Operations) | Compose, ports, trend tick, honesty |
| [Security and Compliance](Security-and-Compliance) | Disclosure, residency posture |

## Product invariants

- **Prove every signal** — durable audit / graph edges, not vendor scorecards.
- **`decision-api` decides** — Rust JSON packs via `tarka_rule_engine`.
- **Shadow / investigation / trend advise** — never silent FLAG→ALLOW or Wasm auto-promote.
- **Offline / no live-tenant fantasy** — demos and holdouts are local fixtures.

## Canonical docs (repo)

- Hub: [`docs/INDEX.md`](https://github.com/pamu512/tarka/blob/master/docs/INDEX.md)
- Flows: [`docs/docs/guides/feature-data-flows.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/feature-data-flows.md)
- Honesty: [`STUB_REGISTER.md`](https://github.com/pamu512/tarka/blob/master/STUB_REGISTER.md)
- Vision: [`VISION.md`](https://github.com/pamu512/tarka/blob/master/VISION.md)

**Source:** [pamu512/tarka](https://github.com/pamu512/tarka) · track **1.3.0-beta** on `master`.
