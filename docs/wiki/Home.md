# Tarka Wiki

Short operator mirror of the repo docs hub. **Canonical source:** [`docs/INDEX.md`](https://github.com/pamu512/tarka/blob/master/docs/INDEX.md) in the main repo.

**Last synced with repo:** 2026-08-17 · track **1.3.0-beta** on `master`.

## Start here

| Page | Purpose |
|------|---------|
| [Quickstart](Quickstart) | Lite / fraud-desk → first evaluate |
| [Architecture](Architecture) | Services, stores, authority |
| [Services](Services) | What each process does |
| [Decision accountability graph](Decision-Accountability-Graph) | Evaluate → advise → disposition chains |
| [Rules and Simulation](Rules-and-Simulation) | Packs, backtest, promote |
| [Operations](Operations) | Compose profiles, ports, trend tick |
| [Security and Compliance](Security-and-Compliance) | Disclosure, residency posture |

## Product invariants

- **Prove every signal** — durable audit / graph edges, not vendor scorecards.
- **`decision-api` decides** — Rust JSON packs via `tarka_rule_engine`.
- **Shadow / investigation / trend advise** — never silent FLAG→ALLOW or Wasm auto-promote.
- **Decision graph records accountability** — fail-soft writers; never overrides allow/deny.
- **Offline / no live-tenant fantasy** — demos and holdouts are local fixtures.

## Canonical docs (repo)

| Doc | Link |
|-----|------|
| Hub | [`docs/INDEX.md`](https://github.com/pamu512/tarka/blob/master/docs/INDEX.md) |
| Quickstart | [`docs/docs/quickstart.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/quickstart.md) |
| Feature flows | [`docs/docs/guides/feature-data-flows.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/feature-data-flows.md) |
| Decision graph | [`docs/docs/guides/decision-context-graph.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/decision-context-graph.md) |
| Honesty | [`STUB_REGISTER.md`](https://github.com/pamu512/tarka/blob/master/docs/STUB_REGISTER.md) |
| Vision | [`VISION.md`](https://github.com/pamu512/tarka/blob/master/VISION.md) |

**Repo:** [pamu512/tarka](https://github.com/pamu512/tarka)

Maintainers: refresh this wiki from `docs/wiki/` in the repo — `scripts/docs/sync-github-wiki.sh`.
