# Rules and Simulation

- Production evaluate uses **Rust JSON packs** (`tarka_rule_engine`), not the legacy Python demo ruleset (gated by `RULE_ENGINE_ALLOW_DEMO_FALLBACK`).
- Simulation / backtest / promote gates live under decision-api ops (`backtest_promote_gate`, typology ops).
- Humans promote via GitOps; trend drafts require HIL — no silent Wasm auto-promote.

Guides:

- [`rules.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/rules.md)
- [`backtest-before-promote.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/backtest-before-promote.md)
- [`shadow-and-ab-testing.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/shadow-and-ab-testing.md)
